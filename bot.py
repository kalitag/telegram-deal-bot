import logging
import re
import asyncio
import aiohttp
from typing import Optional, Dict, List, Any
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
from telegram.constants import ParseMode

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot Configuration
BOT_TOKEN = "8465346144:AAGSHC77UkXVZZTUscbYItvJxgQbBxmFcWo"
BOT_USERNAME = "@tg_workbot"

# URL shorteners list
SHORTENERS = [
    'cutt.ly', 'spoo.me', 'amzn.to', 'amzn-to.co', 'fkrt.cc', 'bitli.in', 
    'da.gd', 'wishlink.com', 'bit.ly', 'tinyurl.com', 'short.link', 
    'ow.ly', 'is.gd', 't.co', 'goo.gl', 'rb.gy', 'tiny.cc', 'v.gd',
    'x.co', 'buff.ly', 'short.gy', 'shorte.st', 'adf.ly', 'bc.vc',
    'tinycc.com', 'shorturl.at', 'clck.ru', '0rz.tw', '1link.in'
]

# Gender detection patterns
GENDER_KEYWORDS = {
    'Men': [
        r'\bmen\b', r"\bmen's\b", r'\bmale\b', r'\bboy\b', r'\bboys\b', 
        r'\bgents\b', r'\bgentleman\b', r'\bmasculine\b', r'\bmans\b', 
        r'\bguys\b', r'\bhim\b', r'\bhis\b', r'\bfather\b', r'\bdad\b'
    ],
    'Women': [
        r'\bwomen\b', r"\bwomen's\b", r'\bfemale\b', r'\bgirl\b', r'\bgirls\b', 
        r'\bladies\b', r'\blady\b', r'\bfeminine\b', r'\bwomens\b', 
        r'\bher\b', r'\bshe\b', r'\bmother\b', r'\bmom\b'
    ],
    'Kids': [
        r'\bkids\b', r'\bchildren\b', r'\bchild\b', r'\bbaby\b', r'\binfant\b', 
        r'\btoddler\b', r'\bteen\b', r'\bteenage\b', r'\bjunior\b', r'\byouth\b'
    ]
}

# Quantity patterns
QUANTITY_PATTERNS = [
    r'pack\s+of\s+(\d+)',
    r'(\d+)\s*pack',
    r'set\s+of\s+(\d+)',
    r'(\d+)\s*pcs?',
    r'(\d+)\s*pieces?',
    r'(\d+)\s*kg',
    r'(\d+)\s*g(?:ram)?s?',
    r'(\d+)\s*ml',
    r'(\d+)\s*l(?:itr?e)?s?',
    r'combo\s+(\d+)',
    r'(\d+)\s*pair',
    r'multipack\s+(\d+)',
    r'quantity\s*:\s*(\d+)'
]

# Known brands
KNOWN_BRANDS = [
    'Lakme', 'Maybelline', 'L\'Oreal', 'MAC', 'Revlon', 'Nykaa', 'Colorbar',
    'Nike', 'Adidas', 'Puma', 'Reebok', 'Converse', 'Vans',
    'Samsung', 'Apple', 'OnePlus', 'Xiaomi', 'Realme', 'Oppo', 'Vivo',
    'Zara', 'H&M', 'Forever21', 'Mango', 'Uniqlo',
    'Mamaearth', 'Wow', 'Biotique', 'Himalaya', 'Patanjali',
    'Jockey', 'Calvin Klein', 'Tommy Hilfiger', 'Allen Solly'
]

class SmartLinkProcessor:
    """Smart link detection and processing"""
    
    @staticmethod
    def extract_all_links(text: str) -> List[str]:
        """Extract all URLs from text"""
        if not text:
            return []
        
        urls = []
        
        # Standard HTTP/HTTPS URLs
        standard_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+(?=[.\s]|$)'
        urls.extend(re.findall(standard_pattern, text, re.IGNORECASE))
        
        # URLs with www
        www_pattern = r'www\.[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:/[^\s<>"{}|\\^`\[\]]*)?'
        potential_urls = re.findall(www_pattern, text)
        for url in potential_urls:
            if not url.startswith('http'):
                url = 'https://' + url
            urls.append(url)
        
        # Platform-specific domains
        domain_patterns = [
            r'(?:amazon\.in|amazon\.com)/[^\s<>"{}|\\^`\[\]]+',
            r'(?:flipkart\.com)/[^\s<>"{}|\\^`\[\]]+',
            r'(?:meesho\.com)/[^\s<>"{}|\\^`\[\]]+',
            r'(?:myntra\.com)/[^\s<>"{}|\\^`\[\]]+',
            r'(?:ajio\.com)/[^\s<>"{}|\\^`\[\]]+',
            r'(?:snapdeal\.com)/[^\s<>"{}|\\^`\[\]]+'
        ]
        
        for pattern in domain_patterns:
            found_urls = re.findall(pattern, text, re.IGNORECASE)
            for url in found_urls:
                if not url.startswith('http'):
                    url = 'https://' + url
                urls.append(url)
        
        # Shortened URLs
        short_pattern = r'(?:https?://)?(?:' + '|'.join(re.escape(s) for s in SHORTENERS) + r')/[^\s<>"{}|\\^`\[\]]+'
        shortened_urls = re.findall(short_pattern, text, re.IGNORECASE)
        
        for url in shortened_urls:
            if not url.startswith('http'):
                url = 'https://' + url
            urls.append(url)
        
        # Clean URLs
        cleaned_urls = []
        seen = set()
        
        for url in urls:
            url = re.sub(r'[.,;:!?\)\]]+$', '', url)
            if url and url not in seen and len(url) > 10 and '.' in url:
                cleaned_urls.append(url)
                seen.add(url)
        
        logger.info(f"Extracted {len(cleaned_urls)} unique URLs")
        return cleaned_urls
    
    @staticmethod
    def is_shortened_url(url: str) -> bool:
        """Check if URL is shortened"""
        try:
            domain = urlparse(url).netloc.lower()
            return any(shortener in domain for shortener in SHORTENERS)
        except:
            return False
    
    @staticmethod
    async def unshorten_url_aggressive(url: str, session: aiohttp.ClientSession) -> str:
        """Unshorten URL aggressively"""
        max_attempts = 3
        current_url = url
        
        for attempt in range(max_attempts):
            try:
                logger.info(f"Unshortening attempt {attempt + 1}: {current_url}")
                
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Connection': 'keep-alive'
                }
                
                # Try HEAD request first
                try:
                    async with session.head(
                        current_url, 
                        allow_redirects=True, 
                        timeout=aiohttp.ClientTimeout(total=10),
                        headers=headers
                    ) as response:
                        final_url = str(response.url)
                        if final_url != current_url and len(final_url) > len(current_url):
                            logger.info(f"HEAD unshorten successful: {final_url}")
                            current_url = final_url
                            break
                except:
                    pass
                
                # Fallback to GET
                try:
                    async with session.get(
                        current_url,
                        allow_redirects=True,
                        timeout=aiohttp.ClientTimeout(total=15),
                        headers=headers
                    ) as response:
                        final_url = str(response.url)
                        if final_url != current_url and len(final_url) > len(current_url):
                            logger.info(f"GET unshorten successful: {final_url}")
                            current_url = final_url
                            break
                except:
                    pass
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.warning(f"Unshorten attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(0.5)
        
        return current_url
    
    @staticmethod
    def clean_affiliate_url_aggressive(url: str) -> str:
        """Clean affiliate parameters from URL"""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            # Amazon cleaning
            if 'amazon' in domain:
                asin_patterns = [
                    r'/dp/([A-Z0-9]{10})(?:/|$|\?)',
                    r'/product/([A-Z0-9]{10})(?:/|$|\?)',
                    r'/([A-Z0-9]{10})(?:/|$|\?)',
                    r'asin=([A-Z0-9]{10})',
                    r'/gp/product/([A-Z0-9]{10})'
                ]
                
                full_path = parsed.path + '?' + parsed.query
                for pattern in asin_patterns:
                    match = re.search(pattern, full_path)
                    if match:
                        asin = match.group(1)
                        return f"https://www.amazon.in/dp/{asin}"
                
                # Fallback clean
                query_params = parse_qs(parsed.query)
                essential_params = {}
                for key, value in query_params.items():
                    if key.lower() in ['keywords', 'field-keywords']:
                        essential_params[key] = value[0]
                
                clean_query = urlencode(essential_params)
                return urlunparse(parsed._replace(query=clean_query))
            
            # Flipkart cleaning
            elif 'flipkart' in domain:
                pid_patterns = [
                    r'/p/[^/]+/([^/?]+)',
                    r'pid=([A-Z0-9]+)',
                    r'/([A-Z0-9]{16})(?:/|\?|$)'
                ]
                
                full_path = parsed.path + '?' + parsed.query
                for pattern in pid_patterns:
                    match = re.search(pattern, full_path)
                    if match:
                        pid = match.group(1)
                        return f"https://www.flipkart.com/p/{pid}"
                
                query_params = parse_qs(parsed.query)
                essential_params = {}
                for key, value in query_params.items():
                    if key.lower() in ['pid', 'lid']:
                        essential_params[key] = value[0]
                
                clean_query = urlencode(essential_params)
                return urlunparse(parsed._replace(query=clean_query))
            
            # Meesho cleaning
            elif 'meesho' in domain:
                return urlunparse(parsed._replace(query=''))
            
            # Myntra cleaning
            elif 'myntra' in domain:
                product_match = re.search(r'/(\d+)', parsed.path)
                if product_match:
                    product_id = product_match.group(1)
                    return f"https://www.myntra.com/{product_id}"
                return urlunparse(parsed._replace(query=''))
            
            # Ajio cleaning
            elif 'ajio' in domain:
                return urlunparse(parsed._replace(query=''))
            
            # Generic cleaning
            else:
                query_params = parse_qs(parsed.query)
                affiliate_keywords = [
                    'utm_', 'ref', 'tag', 'affiliate', 'aff', 'partner', 
                    'source', 'medium', 'campaign', 'tracking', 'fbclid',
                    'gclid', 'mc_', 'zanpid', 'ranMID', 'ranEAID'
                ]
                
                clean_params = {}
                for key, value in query_params.items():
                    if not any(keyword in key.lower() for keyword in affiliate_keywords):
                        clean_params[key] = value[0]
                
                clean_query = urlencode(clean_params)
                return urlunparse(parsed._replace(query=clean_query))
            
        except Exception as e:
            logger.warning(f"Error cleaning URL {url}: {e}")
            return url
        
        return url

class MessageParser:
    """Parse manual product info from messages"""
    
    @staticmethod
    def extract_manual_info(message: str) -> Dict[str, Any]:
        """Extract product info from message text"""
        info = {
            'title': '',
            'price': '',
            'brand': '',
            'gender': '',
            'quantity': '',
            'pin': ''
        }
        
        # Extract price
        price_patterns = [
            r'@\s*(\d+)\s*rs',
            r'₹\s*(\d+(?:,\d+)*)',
            r'Rs\.?\s*(\d+(?:,\d+)*)',
            r'price[:\s]+(\d+(?:,\d+)*)',
            r'(\d+)\s*rs\b'
        ]
        
        for pattern in price_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                price_str = match.group(1).replace(',', '')
                try:
                    price_num = int(price_str)
                    if 10 <= price_num <= 1000000:
                        info['price'] = str(price_num)
                        break
                except:
                    continue
        
        # Extract PIN
        pin_pattern = r'\b([1-9]\d{5})\b'
        pin_matches = re.findall(pin_pattern, message)
        for pin in pin_matches:
            if pin[0] in '123456789':
                info['pin'] = pin
                break
        
        # Extract brand
        message_lower = message.lower()
        for brand in KNOWN_BRANDS:
            if brand.lower() in message_lower:
                info['brand'] = brand
                break
        
        # Extract gender
        for gender, patterns in GENDER_KEYWORDS.items():
            for pattern in patterns:
                if re.search(pattern, message, re.IGNORECASE):
                    info['gender'] = gender
                    break
            if info['gender']:
                break
        
        # Extract quantity
        for pattern in QUANTITY_PATTERNS:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                if len(match.groups()) > 0:
                    quantity = match.group(1)
                else:
                    quantity = match.group(0)
                info['quantity'] = quantity.strip()
                break
        
        # Extract title
        title = message
        title = re.sub(r'https?://[^\s]+', '', title)
        for pattern in price_patterns:
            title = re.sub(pattern, '', title, flags=re.IGNORECASE)
        title = re.sub(r'\b\d{6}\b', '', title)
        title = ' '.join(title.split())
        
        if title and len(title) > 3:
            info['title'] = title[:60].strip()
        
        return info

class ProductScraper:
    """Product information scraper"""
    
    @staticmethod
    def detect_platform(url: str) -> str:
        """Detect platform from URL"""
        domain = urlparse(url).netloc.lower()
        
        if 'amazon' in domain:
            return 'amazon'
        elif 'flipkart' in domain:
            return 'flipkart'
        elif 'meesho' in domain:
            return 'meesho'
        elif 'myntra' in domain:
            return 'myntra'
        elif 'ajio' in domain:
            return 'ajio'
        elif 'snapdeal' in domain:
            return 'snapdeal'
        else:
            return 'generic'
    
    @staticmethod
    async def scrape_with_fallback(url: str, session: aiohttp.ClientSession, manual_info: Dict = None) -> Dict[str, Any]:
        """Scrape product info with fallbacks"""
        platform = ProductScraper.detect_platform(url)
        
        result = {
            'title': '',
            'price': '',
            'sizes': [],
            'brand': '',
            'gender': '',
            'quantity': '',
            'pin': '',
            'platform': platform,
            'error': None
        }
        
        # Apply manual info first
        if manual_info:
            for key, value in manual_info.items():
                if value:
                    result[key] = value
        
        # Try scraping
        scraped_info = await ProductScraper._try_scraping_methods(url, session, platform)
        
        # Merge scraped info
        for key, value in scraped_info.items():
            if value and not result.get(key):
                result[key] = value
        
        # Validate result
        if not result.get('title') and not result.get('price'):
            result['error'] = 'Could not extract product information'
            if 'amazon' in url:
                result['title'] = 'Amazon Product'
            elif 'flipkart' in url:
                result['title'] = 'Flipkart Product'
            elif 'meesho' in url:
                result['title'] = 'Meesho Product'
            else:
                result['title'] = 'Product Deal'
        
        return result
    
    @staticmethod
    async def _try_scraping_methods(url: str, session: aiohttp.ClientSession, platform: str) -> Dict[str, Any]:
        """Try multiple scraping methods"""
        info = {
            'title': '',
            'price': '',
            'sizes': [],
            'brand': '',
            'gender': '',
            'quantity': '',
            'pin': ''
        }
        
        headers_list = [
            {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9,hi;q=0.8',
                'Connection': 'keep-alive'
            },
            {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            }
        ]
        
        for i, headers in enumerate(headers_list):
            try:
                logger.info(f"Scraping attempt {i+1} for {platform}")
                
                async with session.get(
                    url, 
                    headers=headers, 
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as response:
                    
                    if response.status == 200:
                        html = await response.text()
                        
                        if len(html) > 1000:
                            extracted_info = ProductScraper._extract_from_html(html, platform, url)
                            
                            for key, value in extracted_info.items():
                                if value and not info.get(key):
                                    info[key] = value
                            
                            if info.get('title') or info.get('price'):
                                logger.info(f"Successfully extracted data on attempt {i+1}")
                                break
                    else:
                        logger.warning(f"HTTP {response.status} for {url}")
                        
            except Exception as e:
                logger.warning(f"Scraping attempt {i+1} failed: {e}")
                continue
            
            await asyncio.sleep(1)
        
        return info
    
    @staticmethod
    def _extract_from_html(html: str, platform: str, url: str = '') -> Dict[str, Any]:
        """Extract product info from HTML"""
        soup = BeautifulSoup(html, 'html.parser')
        info = {}
        
        # Title extraction
        title_selectors = {
            'amazon': [
                '#productTitle',
                'h1.a-size-large.a-spacing-none.a-color-base',
                'span#productTitle',
                '.product-title',
                'meta[property="og:title"]'
            ],
            'flipkart': [
                '.B_NuCI',
                '._35KyD6',
                'h1.yhB1nd',
                '.fsXA5P',
                'h1',
                'meta[property="og:title"]'
            ],
            'meesho': [
                '[data-testid="product-title"]',
                '.product-title',
                'h1',
                '.sc-bcXHqe',
                'meta[property="og:title"]'
            ],
            'myntra': [
                '.pdp-name',
                '.pdp-title',
                'h1.pdp-name',
                '.product-brand-name',
                'meta[property="og:title"]'
            ],
            'ajio': [
                '.prod-name',
                '.product-name',
                'h1.prod-title',
                'meta[property="og:title"]'
            ],
            'generic': [
                'h1',
                '.product-name',
                '.product-title',
                'meta[property="og:title"]',
                'title'
            ]
        }
        
        selectors = title_selectors.get(platform, title_selectors['generic'])
        for selector in selectors:
            try:
                elements = soup.select(selector)
                for element in elements:
                    if selector.startswith('meta'):
                        text = element.get('content', '').strip()
                    else:
                        text = element.get_text(strip=True)
                    
                    if text and len(text) > 5 and len(text) < 200:
                        cleaned_title = ProductScraper._clean_title(text)
                        if cleaned_title:
                            info['title'] = cleaned_title
                            break
                
                if info.get('title'):
                    break
            except:
                continue
        
        # Price extraction
        price_patterns = [
            r'[₹]\s*(\d+(?:,\d+)*)',
            r'"price"[:\s]*"?(\d+(?:,\d+)*)',
            r'₹(\d+(?:,\d+)*)',
            r'Rs\.?\s*(\d+(?:,\d+)*)',
            r'\bprice["\s]*[:=]\s*["\s]*(\d+(?:,\d+)*)',
            r'MRP[:\s]*[₹Rs\.]*\s*(\d+(?:,\d+)*)',
            r'current[_\s]*price["\s]*[:=]\s*["\s]*(\d+(?:,\d+)*)'
        ]
        
        # Try selector-based extraction first
        price_selectors = {
            'amazon': ['.a-price-whole', '.a-price .a-offscreen', '.a-price-range'],
            'flipkart': ['._30jeq3', '._1_WHN1', '.CEmiEU'],
            'meesho': ['.price', '.current-price'],
            'myntra': ['.pdp-price', '.price-current'],
            'ajio': ['.prod-price', '.price-current']
        }
        
        if platform in price_selectors:
            for selector in price_selectors[platform]:
                try:
                    elements = soup.select(selector)
                    for element in elements:
                        text = element.get_text(strip=True)
                        price_match = re.search(r'(\d+(?:,\d+)*)', text)
                        if price_match:
                            price_num = int(price_match.group(1).replace(',', ''))
                            if 10 <= price_num <= 1000000:
                                info['price'] = str(price_num)
                                break
                    if info.get('price'):
                        break
                except:
                    continue
        
        # Fallback to regex patterns
        if not info.get('price'):
            for pattern in price_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                for match in matches:
                    try:
                        price_num = int(match.replace(',', ''))
                        if 10 <= price_num <= 1000000:
                            info['price'] = str(price_num)
                            break
                    except:
                        continue
                if info.get('price'):
                    break
        
        # Platform-specific extractions
        if platform == 'meesho':
            # Extract sizes
            size_patterns = [
                r'\b(XS|S|M|L|XL|XXL|XXXL|2XL|3XL)\b',
                r'\bSize[:\s]+(XS|S|M|L|XL|XXL|XXXL|2XL|3XL)\b'
            ]
            sizes = set()
            for pattern in size_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE)
                for match in matches:
                    sizes.add(match.upper())
                    if len(sizes) >= 5:
                        break
            
            if sizes:
                info['sizes'] = sorted(list(sizes))
            
            # Extract PIN
            pin_matches = re.findall(r'\b([1-9]\d{5})\b', html)
            for pin in pin_matches[:3]:
                if pin.startswith(tuple('123456789')):
                    info['pin'] = pin
                    break
        
        # Extract brand from title
        if info.get('title'):
            title_lower = info['title'].lower()
            for brand in KNOWN_BRANDS:
                if brand.lower() in title_lower:
                    info['brand'] = brand
                    break
        
        # Extract gender from title
        if info.get('title'):
            title_lower = info['title'].lower()
            for gender, patterns in GENDER_KEYWORDS.items():
                for pattern in patterns:
                    if re.search(pattern, title_lower):
                        info['gender'] = gender
                        break
                if info.get('gender'):
                    break
        
        # Extract quantity from title
        if info.get('title'):
            for pattern in QUANTITY_PATTERNS:
                match = re.search(pattern, info['title'], re.IGNORECASE)
                if match:
                    if len(match.groups()) > 0:
                        info['quantity'] = match.group(1)
                    else:
                        info['quantity'] = match.group(0).strip()
                    break
        
        return info
    
    @staticmethod
    def _clean_title(title: str) -> str:
        """Clean title text"""
        if not title:
            return ''
        
        # Remove platform-specific noise
        noise_patterns = [
            r'\s*-\s*Amazon\.in.*$',
            r'\s*:\s*Amazon\.in.*$',
            r'\s*\|\s*Flipkart\.com.*$',
            r'\s*-\s*Buy.*$',
            r'\s*\|\s*Buy.*$',
            r'Buy\s+.*?online.*?at.*?price.*?$',
            r'Shop\s+.*?online.*?$',
            r'\s*\|\s*Myntra.*$',
            r'\s*-\s*Meesho.*$',
            r'\s*\|\s*.*\.com.*$',
            r'\s*-\s*.*\.in.*$',
            r'MRP.*?₹.*?\d+',
            r'Price.*?₹.*?\d+',
            r'₹\d+.*?off',
            r'\d+%.*?off',
            r'discount.*?\d+',
            r'save.*?₹.*?\d+'
        ]
        
        clean_title = title
        for pattern in noise_patterns:
            clean_title = re.sub(pattern, '', clean_title, flags=re.IGNORECASE)
        
        # Remove extra whitespace and clean up
        clean_title = ' '.join(clean_title.split())
        
        # Remove promotional and price words
        promo_words = [
            'offer', 'deal', 'sale', 'discount', 'exclusive', 'limited', 'special',
            'mrp', 'price', 'rs', 'rupees', 'off', 'save', 'best', 'lowest',
            'original', 'authentic', 'genuine', 'brand', 'new', 'latest'
        ]
        words = clean_title.split()
        filtered_words = []
        
        for word in words:
            # ✅ Add this line to define the promotional words you want to skip.
promo_words = {"deal", "offer", "sale", "special", "discount", "free", "limited", "new"}

# ===== Helper Functions =====
def clean_title(raw_title: str) -> str:
    """
    Cleans product titles by removing platform-specific noise, promo words, repeated words,
    and unnecessary symbols. Ensures brand and essential details remain.
    """
    noise_words = {
        "deal", "offer", "sale", "special", "discount", "free", "limited", "new",
        "buy", "shop", "trending", "exclusive", "best price", "hot"
    }
    # Lowercase comparison for cleaning but keep original case for display
    title_words = raw_title.split()
    cleaned_words = []
    for word in title_words:
        if word.lower() not in noise_words and not re.match(r'^\W+$', word):
            cleaned_words.append(word)
    # Remove duplicates while preserving order
    seen = set()
    final_words = [w for w in cleaned_words if not (w.lower() in seen or seen.add(w.lower()))]
    return " ".join(final_words).strip()

def extract_price(text: str) -> str:
    """
    Extracts the actual selling price from a string, ignoring MRP/discount info.
    """
    matches = re.findall(r'₹\s?(\d+)', text)
    if matches:
        prices = sorted(set(int(p) for p in matches))
        return f"₹{prices[0]}" if prices else ""
    return ""

def detect_brand_gender_qty(title: str) -> dict:
    """
    Detects brand, gender, and quantity from product title.
    """
    brand_match = re.search(r'by\s+([A-Za-z0-9]+)', title, re.IGNORECASE)
    gender = "Unisex"
    if re.search(r'\bmen\b', title, re.IGNORECASE):
        gender = "Men"
    elif re.search(r'\bwomen\b', title, re.IGNORECASE):
        gender = "Women"

    qty_match = re.search(r'(\d+)\s?(pcs|pieces|pack)', title, re.IGNORECASE)
    return {
        "brand": brand_match.group(1) if brand_match else "",
        "gender": gender,
        "quantity": qty_match.group(0) if qty_match else ""
    }

def unshorten_url(url: str) -> str:
    """
    Expands shortened URLs to their final destination.
    """
    try:
        r = requests.head(url, allow_redirects=True, timeout=5)
        return r.url
    except requests.RequestException:
        return url

def extract_text_from_image(image_path: str) -> str:
    """
    Uses OCR to extract text from an image.
    """
    try:
        img = Image.open(image_path)
        return pytesseract.image_to_string(img)
    except Exception:
        return ""

# ===== Processing Items =====
async def process_item(item):
    promo_words = {"deal", "offer", "sale", "special", "discount", "free", "limited", "new"}

    title = clean_title(item.get("title", ""))
    price = extract_price(item.get("price_info", ""))
    meta = detect_brand_gender_qty(title)

    # Meesho-specific additions
    if "meesho.com" in item.get("url", "").lower():
        if "size" in item:
            title += f" | Size: {item['size']}"
        if "pin" in item:
            title += f" | PIN: {item['pin']}"

    return {
        "title": title,
        "price": price,
        "brand": meta["brand"],
        "gender": meta["gender"],
        "quantity": meta["quantity"],
        "url": unshorten_url(item.get("url", ""))
    }

# ===== Example Usage =====
# Assuming 'items' is a list of dictionaries with keys: title, price_info, url, size, pin
async def process_all_items(items):
    results = []
    for item in items:
        result = await process_item(item)
        results.append(result)
    return results
        
        # Limit length smartly
        if len(clean_title) > 60:
            clean_title = clean_title[:60]
            if ' ' in clean_title:
                clean_title = clean_title.rsplit(' ', 1)[0] + '...'
        
        return clean_title.strip()

class DealFormatter:
    """Format deals according to specifications"""
    
    @staticmethod
    def format_deal(product_info: Dict[str, Any], clean_url: str, platform: str = '') -> str:
        """Format product info into deal structure"""
        
        if not platform:
            platform = ProductScraper.detect_platform(clean_url)
        
        # Build first line components
        line_components = []
        
        # Brand (if available and not in title)
        brand = product_info.get('brand', '').strip()
        title = product_info.get('title', '').strip()
        
        if brand and brand.lower() not in title.lower():
            line_components.append(brand)
        
        # Gender
        gender = product_info.get('gender', '').strip()
        if gender:
            line_components.append(gender)
        
        # Quantity
        quantity = product_info.get('quantity', '').strip()
        if quantity:
            line_components.append(quantity)
        
        # Title (cleaned)
        if title:
            # Remove brand from title if already added
            if brand and brand.lower() in title.lower():
                title_words = title.split()
                filtered_words = []
                brand_words = brand.lower().split()
                
                i = 0
                while i < len(title_words):
                    word = title_words[i].lower()
                    if word in [b.lower() for b in brand_words]:
                        # Skip brand words
                        brand_match = True
                        for j, brand_word in enumerate(brand_words):
                            if i + j >= len(title_words) or title_words[i + j].lower() != brand_word.lower():
                                brand_match = False
                                break
                        if brand_match:
                            i += len(brand_words)
                            continue
                    filtered_words.append(title_words[i])
                    i += 1
                
                title = ' '.join(filtered_words).strip()
            
            line_components.append(title)
        else:
            line_components.append('Product Deal')
        
        # Price
        price = product_info.get('price', '').strip()
        if price:
            line_components.append(f"@{price} rs")
        
        # Build message
        lines = []
        
        # First line: all components
        first_line = ' '.join(line_components)
        lines.append(first_line)
        
        # Second line: clean URL
        lines.append(clean_url)
        
        # Third line: empty
        lines.append('')
        
        # Meesho-specific info
        if platform == 'meesho' or 'meesho' in clean_url.lower():
            # Size info
            sizes = product_info.get('sizes', [])
            if sizes:
                if len(sizes) >= 5:
                    lines.append('Size - All')
                else:
                    lines.append(f"Size - {', '.join(sizes)}")
            else:
                lines.append('Size - All')
            
            # PIN info
            pin = product_info.get('pin', '110001')
            lines.append(f"Pin - {pin}")
            
            # Empty line
            lines.append('')
        
        # Channel tag
        lines.append('@reviewcheckk')
        
        return '\n'.join(lines)

class DealBot:
    """Main bot class"""
    
    def __init__(self):
        self.session = None
        self.processed_messages = set()
        self.processing_lock = asyncio.Lock()
    
    async def initialize(self):
        """Initialize session"""
        if not self.session:
            connector = aiohttp.TCPConnector(
                limit=30,
                limit_per_host=10,
                ttl_dns_cache=300,
                use_dns_cache=True
            )
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'}
            )
    
    async def cleanup(self):
        """Cleanup resources"""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def process_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process incoming messages"""
        async with self.processing_lock:
            try:
                message = update.message or update.channel_post
                if not message:
                    return
                
                # Prevent duplicate processing
                message_id = f"{message.chat_id}_{message.message_id}"
                if message_id in self.processed_messages:
                    return
                
                self.processed_messages.add(message_id)
                
                # Memory management
                if len(self.processed_messages) > 200:
                    old_messages = list(self.processed_messages)[:100]
                    for old_msg in old_messages:
                        self.processed_messages.discard(old_msg)
                
                await self.initialize()
                
                # Extract text
                text = message.text or message.caption or ''
                if not text or len(text.strip()) < 5:
                    return
                
                logger.info(f"Processing message: {text[:100]}...")
                
                # Extract links
                links = SmartLinkProcessor.extract_all_links(text)
                
                if not links:
                    logger.info("No links found")
                    return
                
                logger.info(f"Found {len(links)} links")
                
                # Process each link
                results = []
                for i, url in enumerate(links):
                    try:
                        logger.info(f"Processing link {i+1}/{len(links)}: {url}")
                        
                        # Unshorten if needed
                        if SmartLinkProcessor.is_shortened_url(url):
                            logger.info(f"Unshortening URL: {url}")
                            url = await SmartLinkProcessor.unshorten_url_aggressive(url, self.session)
                            logger.info(f"Unshortened to: {url}")
                        
                        # Clean URL
                        clean_url = SmartLinkProcessor.clean_affiliate_url_aggressive(url)
                        logger.info(f"Cleaned URL: {clean_url}")
                        
                        # Extract manual info
                        manual_info = MessageParser.extract_manual_info(text)
                        logger.info(f"Manual info: {manual_info}")
                        
                        # Scrape product info
                        product_info = await ProductScraper.scrape_with_fallback(
                            clean_url, 
                            self.session, 
                            manual_info
                        )
                        logger.info(f"Product info: {product_info}")
                        
                        # Detect platform
                        platform = ProductScraper.detect_platform(clean_url)
                        
                        # Format message
                        formatted_message = DealFormatter.format_deal(product_info, clean_url, platform)
                        
                        results.append(formatted_message)
                        
                        # Brief delay
                        if len(links) > 1 and i < len(links) - 1:
                            await asyncio.sleep(1)
                        
                    except Exception as e:
                        logger.error(f"Error processing link {url}: {str(e)}")
                        error_msg = f"Product Deal\n{url}\n\n@reviewcheckk"
                        results.append(error_msg)
                        continue
                
                # Send results
                for result in results:
                    try:
                        await safe_send_message(
                            update, 
                            context, 
                            result, 
                            disable_web_page_preview=True
                        )
                        
                        if len(results) > 1:
                            await asyncio.sleep(0.5)
                    except Exception as e:
                        logger.error(f"Failed to send result: {e}")
                        continue
                        
            except Exception as e:
                logger.error(f"Error in process_message: {str(e)}")
                try:
                    error_msg = "❌ Error processing message\n\n@reviewcheckk"
                    await safe_send_message(update, context, error_msg)
                except:
                    pass

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle start command"""
    msg = (
        "🤖 *Deal Bot v2.0 Active!*\n\n"
        "✅ Smart link detection & processing\n"
        "✅ Automatic URL unshortening\n"
        "✅ Clean affiliate link removal\n"
        "✅ Accurate price & title extraction\n"
        "✅ Brand, gender & quantity detection\n"
        "✅ Meesho size & PIN support\n"
        "✅ Strict deal format compliance\n\n"
        "📝 *Supported Platforms:*\n"
        "• Amazon • Flipkart • Meesho\n"
        "• Myntra • Ajio • Snapdeal\n\n"
        "🔗 Send any product link and get perfectly formatted deals!\n\n"
        "@reviewcheckk"
    )
    await safe_send_message(update, context, msg, parse_mode=ParseMode.MARKDOWN)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")
    
    try:
        if update and update.effective_chat:
            await safe_send_message(
                update, 
                context, 
                "❌ Sorry, an error occurred. Please try again.\n\n@reviewcheckk"
            )
    except:
        pass

async def safe_send_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, **kwargs):
    """Safe message sending"""
    if not update or not update.effective_chat:
        logger.error("Invalid update or chat")
        return
    
    try:
        # Ensure text length limit
        if len(text) > 4096:
            text = text[:4090] + "..."
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            **kwargs
        )
        logger.info("Message sent successfully")
        
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Error processing request\n\n@reviewcheckk"
            )
        except Exception as e2:
            logger.error(f"Failed to send fallback message: {e2}")

def main():
    """Main function"""
    print("🚀 Starting Deal Bot v2.0...")
    
    try:
        # Create application
        application = (
            Application.builder()
            .token(BOT_TOKEN)
            .connect_timeout(30)
            .read_timeout(30)
            .write_timeout(30)
            .pool_timeout(30)
            .build()
        )
        
        # Initialize bot
        bot = DealBot()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(MessageHandler(
            filters.TEXT | filters.CAPTION, 
            bot.process_message
        ))
        
        # Add error handler
        application.add_error_handler(error_handler)
        
        # Setup cleanup
        import signal
        import sys
        
        def signal_handler(sig, frame):
            print("\n🛑 Shutting down bot...")
            asyncio.create_task(bot.cleanup())
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Start bot
        print(f"✅ Bot @{BOT_USERNAME} is running...")
        print("📡 Monitoring all channels, groups, and DMs")
        print("🔗 Processing product links with enhanced accuracy")
        print("📝 Strict deal format compliance enabled")
        
        # Run bot
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
        
    except Exception as e:
        print(f"❌ Failed to start bot: {e}")
        logger.error(f"Bot startup failed: {e}")

if __name__ == '__main__':
    main()
