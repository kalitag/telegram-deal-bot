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

# Configure logging (only once)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot Configuration
BOT_TOKEN = "8465346144:AAGSHC77UkXVZZTUscbYItvJxgQbBxmFcWo"
BOT_USERNAME = "@tg_workbot"

# Complete list of URL shorteners
SHORTENERS = [
    'cutt.ly', 'spoo.me', 'amzn.to', 'amzn-to.co', 'fkrt.cc', 'bitli.in', 
    'da.gd', 'wishlink.com', 'bit.ly', 'tinyurl.com', 'short.link', 
    'ow.ly', 'is.gd', 't.co', 'goo.gl', 'rb.gy', 'tiny.cc', 'v.gd',
    'x.co', 'buff.ly', 'short.gy', 'shorte.st', 'adf.ly', 'bc.vc'
]

# Enhanced gender detection
GENDER_KEYWORDS = {
    'Men': [
        'men', "men's", 'male', 'boy', 'boys', 'gents', 'gentleman', 
        'masculine', 'mans', 'guys', 'him', 'his'
    ],
    'Women': [
        'women', "women's", 'female', 'girl', 'girls', 'ladies', 'lady', 
        'feminine', 'womens', 'her', 'she', 'girls'
    ],
    'Kids': [
        'kids', 'children', 'child', 'baby', 'infant', 'toddler', 
        'teen', 'teenage', 'junior', 'youth'
    ],
    'Unisex': ['unisex', 'universal', 'both', 'all genders']
}

# Enhanced quantity patterns
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

# Common brands to prioritize
KNOWN_BRANDS = [
    'Lakme', 'Maybelline', 'L\'Oreal', 'MAC', 'Revlon', 'Nykaa', 'Colorbar',
    'Nike', 'Adidas', 'Puma', 'Reebok', 'Converse', 'Vans',
    'Samsung', 'Apple', 'OnePlus', 'Xiaomi', 'Realme', 'Oppo', 'Vivo',
    'Zara', 'H&M', 'Forever21', 'Mango', 'Uniqlo',
    'Mamaearth', 'Wow', 'Biotique', 'Himalaya', 'Patanjali'
]

class SmartLinkProcessor:
    """Ultra-smart link detection and processing"""
    
    @staticmethod
    def extract_all_links(text: str) -> List[str]:
        """Extract ALL possible URLs from text - no link should be missed"""
        if not text:
            return []
        
        urls = []
        
        # Pattern 1: Standard HTTP/HTTPS URLs
        standard_pattern = r'https?://[^\s<>"{}|\\^`\[\]\(\)]*[^\s<>"{}|\\^`\[\]\(\)\.,;:!?\s]'
        urls.extend(re.findall(standard_pattern, text, re.IGNORECASE))
        
        # Pattern 2: URLs without protocol
        no_protocol_pattern = r'(?:www\.)?[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:/[^\s<>"{}|\\^`\[\]\(\)]*)?'
        potential_urls = re.findall(no_protocol_pattern, text)
        
        for url in potential_urls:
            if any(domain in url for domain in ['amazon', 'flipkart', 'meesho', 'myntra', 'ajio', 'snapdeal']):
                if not url.startswith('http'):
                    url = 'https://' + url
                urls.append(url)
        
        # Pattern 3: Shortened URLs
        short_pattern = r'(?:https?://)?(?:www\.)?(?:' + '|'.join(re.escape(s) for s in SHORTENERS) + r')/[^\s<>"{}|\\^`\[\]\(\)]*'
        shortened_urls = re.findall(short_pattern, text, re.IGNORECASE)
        
        for url in shortened_urls:
            if not url.startswith('http'):
                url = 'https://' + url
            urls.append(url)
        
        # Clean and deduplicate URLs
        cleaned_urls = []
        seen = set()
        
        for url in urls:
            # Remove trailing punctuation
            url = re.sub(r'[.,:;!?\)]+$', '', url)
            
            # Remove duplicates
            if url and url not in seen and len(url) > 10:
                cleaned_urls.append(url)
                seen.add(url)
        
        logger.info(f"Extracted {len(cleaned_urls)} unique URLs: {cleaned_urls}")
        return cleaned_urls
    
    @staticmethod
    def is_shortened_url(url: str) -> bool:
        """Enhanced shortener detection"""
        try:
            domain = urlparse(url).netloc.lower()
            return any(shortener in domain for shortener in SHORTENERS)
        except:
            return False
    
    @staticmethod
    async def unshorten_url_aggressive(url: str, session: aiohttp.ClientSession) -> str:
        """Aggressive URL unshortening with multiple fallbacks"""
        max_attempts = 5
        current_url = url
        
        for attempt in range(max_attempts):
            try:
                logger.info(f"Unshortening attempt {attempt + 1}: {current_url}")
                
                # Method 1: HEAD request
                try:
                    async with session.head(
                        current_url, 
                        allow_redirects=True, 
                        timeout=aiohttp.ClientTimeout(total=15),
                        headers={'User-Agent': 'Mozilla/5.0 (compatible; Bot/1.0)'}
                    ) as response:
                        final_url = str(response.url)
                        if final_url != current_url and 'http' in final_url:
                            logger.info(f"HEAD unshorten: {current_url} -> {final_url}")
                            current_url = final_url
                            continue
                except:
                    pass
                
                # Method 2: GET request with minimal read
                try:
                    async with session.get(
                        current_url,
                        allow_redirects=True,
                        timeout=aiohttp.ClientTimeout(total=15),
                        headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
                        }
                    ) as response:
                        final_url = str(response.url)
                        if final_url != current_url and 'http' in final_url:
                            logger.info(f"GET unshorten: {current_url} -> {final_url}")
                            current_url = final_url
                            break
                except:
                    pass
                
                break
                
            except Exception as e:
                logger.warning(f"Unshorten attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(0.5)
        
        return current_url
    
    @staticmethod
    def clean_affiliate_url_aggressive(url: str) -> str:
        """Ultra-aggressive affiliate cleaning"""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            # Amazon cleaning
            if 'amazon' in domain:
                # Extract ASIN/product ID
                asin_match = re.search(r'/([A-Z0-9]{10})(?:/|$|\?)', parsed.path + '?' + parsed.query)
                if asin_match:
                    asin = asin_match.group(1)
                    return f"https://www.amazon.in/dp/{asin}"
                
                # Fallback: clean query params
                query_params = parse_qs(parsed.query)
                clean_params = {}
                for key, value in query_params.items():
                    if key.lower() not in ['tag', 'ref', 'linkcode', 'linkid', 'psc', 'keywords', 'qid', 'sr']:
                        clean_params[key] = value[0]
                
                clean_query = urlencode(clean_params)
                return urlunparse(parsed._replace(query=clean_query))
            
            # Flipkart cleaning
            elif 'flipkart' in domain:
                # Keep only essential path and remove all query params except pid
                path_parts = [p for p in parsed.path.split('/') if p and 'p-' in p]
                if path_parts:
                    clean_path = '/p/' + path_parts[-1]
                    return f"https://www.flipkart.com{clean_path}"
                
                query_params = parse_qs(parsed.query)
                clean_params = {}
                for key, value in query_params.items():
                    if key.lower() in ['pid']:
                        clean_params[key] = value[0]
                
                clean_query = urlencode(clean_params)
                return urlunparse(parsed._replace(query=clean_query))
            
            # Meesho cleaning
            elif 'meesho' in domain:
                # Remove all query parameters for Meesho
                return urlunparse(parsed._replace(query=''))
            
            # Myntra cleaning
            elif 'myntra' in domain:
                # Keep only product ID part
                product_match = re.search(r'/(\d+)/', parsed.path)
                if product_match:
                    product_id = product_match.group(1)
                    return f"https://www.myntra.com/product/{product_id}"
                return urlunparse(parsed._replace(query=''))
            
            # Ajio cleaning
            elif 'ajio' in domain:
                return urlunparse(parsed._replace(query=''))
            
            # Generic cleaning
            else:
                query_params = parse_qs(parsed.query)
                affiliate_keywords = [
                    'utm_', 'ref', 'tag', 'affiliate', 'aff', 'partner', 
                    'source', 'medium', 'campaign', 'tracking', 'fbclid'
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
    """Parse user messages for manual product info"""
    
    @staticmethod
    def extract_manual_info(message: str) -> Dict[str, Any]:
        """Extract product info from manual message"""
        info = {
            'title': '',
            'price': '',
            'brand': '',
            'gender': '',
            'quantity': '',
            'pin': ''
        }
        
        # Extract price from message
        price_patterns = [
            r'@\s*(\d+)\s*rs',
            r'₹\s*(\d+)',
            r'Rs\.?\s*(\d+)',
            r'price[:\s]+(\d+)'
        ]
        
        for pattern in price_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                info['price'] = match.group(1)
                break
        
        # Extract PIN for Meesho
        pin_match = re.search(r'\b([1-9]\d{5})\b', message)
        if pin_match:
            info['pin'] = pin_match.group(1)
        
        # Extract brand
        for brand in KNOWN_BRANDS:
            if brand.lower() in message.lower():
                info['brand'] = brand
                break
        
        # Extract gender
        message_lower = message.lower()
        for gender, keywords in GENDER_KEYWORDS.items():
            for keyword in keywords:
                if keyword in message_lower:
                    info['gender'] = gender
                    break
        
        # Extract quantity
        for pattern in QUANTITY_PATTERNS:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                info['quantity'] = match.group(0).strip()
                break
        
        # Extract title (clean message text)
        title = message
        # Remove URLs
        title = re.sub(r'https?://[^\s]+', '', title)
        # Remove price
        title = re.sub(r'[@₹]?\s*\d+\s*rs', '', title, flags=re.IGNORECASE)
        # Remove PIN
        title = re.sub(r'\b\d{6}\b', '', title)
        # Clean up
        title = ' '.join(title.split())
        
        if title and len(title) > 3:
            info['title'] = title[:50]
        
        return info

class ProductScraper:
    """Advanced product scraping with multiple fallback methods"""
    
    @staticmethod
    def detect_platform(url: str) -> str:
        """Detect e-commerce platform from URL"""
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
        """Main scraping method with fallbacks"""
        platform = ProductScraper.detect_platform(url)
        
        # Try scraping with different methods
        scraped_info = await ProductScraper._try_scraping_methods(url, session, platform)
        
        # Merge with manual info if available
        if manual_info:
            for key, value in manual_info.items():
                if value and not scraped_info.get(key):
                    scraped_info[key] = value
        
        # Ensure we have at least basic info
        if not scraped_info.get('title') and not scraped_info.get('price'):
            scraped_info['error'] = 'Could not extract product information'
        
        scraped_info['platform'] = platform
        return scraped_info
    
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
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            },
            {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            },
            {
                'User-Agent': 'curl/7.68.0',
                'Accept': '*/*'
            }
        ]
        
        for headers in headers_list:
            try:
                async with session.get(url, headers=headers, timeout=20) as response:
                    if response.status == 200:
                        html = await response.text()
                        extracted_info = ProductScraper._extract_from_html(html, platform)
                        
                        # Merge extracted info
                        for key, value in extracted_info.items():
                            if value and not info.get(key):
                                info[key] = value
                        
                        if info.get('title') or info.get('price'):
                            break
                            
            except Exception as e:
                logger.warning(f"Scraping attempt failed: {e}")
                continue
        
        return info
    
    @staticmethod
    def _extract_from_html(html: str, platform: str) -> Dict[str, Any]:
        """Extract product info from HTML"""
        soup = BeautifulSoup(html, 'html.parser')
        info = {}
        
        # Extract title
        title_selectors = {
            'amazon': ['#productTitle', 'h1.a-size-large', 'meta[property="og:title"]'],
            'flipkart': ['.B_NuCI', '._35KyD6', 'h1', 'meta[property="og:title"]'],
            'meesho': ['[data-testid="product-title"]', 'h1', 'meta[property="og:title"]'],
            'myntra': ['.pdp-name', '.pdp-title', 'h1.pdp-name', 'meta[property="og:title"]'],
            'ajio': ['.prod-name', '.product-name', 'h1', 'meta[property="og:title"]'],
            'generic': ['h1', 'meta[property="og:title"]', 'title']
        }
        
        selectors = title_selectors.get(platform, title_selectors['generic'])
        for selector in selectors:
            try:
                element = soup.select_one(selector)
                if element:
                    if selector.startswith('meta'):
                        text = element.get('content', '').strip()
                    else:
                        text = element.get_text(strip=True)
                    
                    if text and len(text) > 3:
                        info['title'] = ProductScraper._clean_title(text)
                        break
            except:
                continue
        
        # Extract price
        price_patterns = [
            r'[₹Rs\.]\s*(\d+(?:,\d+)*)',
            r'"price"[:\s]*"?(\d+(?:,\d+)*)',
            r'₹(\d+(?:,\d+)*)',
            r'Rs\.?\s*(\d+(?:,\d+)*)'
        ]
        
        for pattern in price_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                for match in matches:
                    price_num = int(match.replace(',', ''))
                    if 10 <= price_num <= 1000000:
                        info['price'] = str(price_num)
                        break
                if info.get('price'):
                    break
        
        # Extract sizes for Meesho
        if platform == 'meesho':
            sizes = set()
            size_pattern = r'\b(S|M|L|XL|XXL|XXXL|2XL|3XL)\b'
            size_matches = re.findall(size_pattern, html)
            for size in size_matches[:10]:  # Limit to first 10 matches
                sizes.add(size)
            info['sizes'] = sorted(list(sizes))
            
            # Extract PIN
            pin_pattern = r'\b([1-9]\d{5})\b'
            pins = re.findall(pin_pattern, html)
            for pin in pins[:5]:  # Check first 5 matches
                if pin.startswith(('1', '2', '3', '4', '5', '6', '7', '8', '9')):
                    info['pin'] = pin
                    break
        
        # Detect brand
        if info.get('title'):
            for brand in KNOWN_BRANDS:
                if brand.lower() in info['title'].lower():
                    info['brand'] = brand
                    break
        
        # Detect gender
        if info.get('title'):
            title_lower = info['title'].lower()
            for gender, keywords in GENDER_KEYWORDS.items():
                for keyword in keywords:
                    if keyword in title_lower:
                        info['gender'] = gender
                        break
        
        # Detect quantity
        if info.get('title'):
            for pattern in QUANTITY_PATTERNS:
                match = re.search(pattern, info['title'], re.IGNORECASE)
                if match:
                    info['quantity'] = match.group(0).strip()
                    break
        
        return info
    
    @staticmethod
    def _clean_title(title: str) -> str:
        """Clean title text"""
        # Remove common e-commerce words
        remove_words = [
            'buy', 'shop', 'online', 'india', 'best', 'price', 'sale',
            'discount', 'offer', 'deal', 'exclusive', 'limited'
        ]
        
        words = title.split()
        filtered = []
        for word in words:
            if word.lower() not in remove_words:
                filtered.append(word)
        
        clean_title = ' '.join(filtered)
        
        # Limit length
        if len(clean_title) > 50:
            clean_title = clean_title[:50].rsplit(' ', 1)[0] + '...'
        
        return clean_title.strip()

class DealFormatter:
    """Format product information according to exact specifications"""
    
    @staticmethod
    def format_deal(product_info: Dict[str, Any], clean_url: str, platform: str = '') -> str:
        """Format product information into exact deal structure"""
        
        # Build first line components
        components = []
        
        # Add brand if available
        if product_info.get('brand'):
            components.append(product_info['brand'])
        
        # Add gender if available
        if product_info.get('gender'):
            components.append(product_info['gender'])
        
        # Add quantity if available
        if product_info.get('quantity'):
            components.append(product_info['quantity'])
        
        # Add title (mandatory)
        if product_info.get('title'):
            components.append(product_info['title'])
        else:
            components.append('Product Deal')
        
        # Add price if available
        if product_info.get('price'):
            components.append(f"@{product_info['price']} rs")
        
        # Build the message
        lines = []
        
        # First line: product info
        if components:
            lines.append(' '.join(components))
        
        # Second line: clean URL
        lines.append(clean_url)
        
        # Empty line
        lines.append('')
        
        # Meesho-specific info
        if platform == 'meesho' or 'meesho' in clean_url.lower():
            # Add sizes
            if product_info.get('sizes'):
                if len(product_info['sizes']) >= 5:
                    lines.append('Size - All')
                else:
                    lines.append(f"Size - {', '.join(product_info['sizes'])}")
            
            # Add PIN
            pin = product_info.get('pin', '110001')
            lines.append(f"Pin - {pin}")
            
            # Empty line before tag
            lines.append('')
        
        # Add channel tag
        lines.append('@reviewcheckk')
        
        return '\n'.join(lines)

class DealBot:
    """Main bot handler"""
    
    def __init__(self):
        self.session = None
        self.processed_messages = set()  # Track processed messages to avoid duplicates
    
    async def initialize(self):
        """Initialize aiohttp session"""
        if not self.session:
            self.session = aiohttp.ClientSession()
    
    async def cleanup(self):
        """Cleanup resources"""
        if self.session:
            await self.session.close()
    
    async def process_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process incoming messages"""
        try:
            message = update.message or update.channel_post
            if not message:
                return
            
            # Avoid processing same message twice
            message_id = f"{message.chat_id}_{message.message_id}"
            if message_id in self.processed_messages:
                return
            self.processed_messages.add(message_id)
            
            # Keep only last 100 message IDs in memory
            if len(self.processed_messages) > 100:
                self.processed_messages = set(list(self.processed_messages)[-50:])
            
            await self.initialize()
            
            # Extract text from message or caption
            text = message.text or message.caption or ''
            
            # Extract all links
            links = SmartLinkProcessor.extract_all_links(text)
            
            if not links:
                logger.info(f"No links found in message: {text[:50]}...")
                return
            
            logger.info(f"Processing {len(links)} links from message")
            
            # Process each link
            for url in links:
                try:
                    # Check if shortened and unshorten
                    if SmartLinkProcessor.is_shortened_url(url):
                        logger.info(f"Unshortening URL: {url}")
                        url = await SmartLinkProcessor.unshorten_url_aggressive(url, self.session)
                    
                    # Clean affiliate tags
                    clean_url = SmartLinkProcessor.clean_affiliate_url_aggressive(url)
                    logger.info(f"Clean URL: {clean_url}")
                    
                    # Extract manual info from message
                    manual_info = MessageParser.extract_manual_info(text)
                    
                    # Scrape product info
                    product_info = await ProductScraper.scrape_with_fallback(
                        clean_url, 
                        self.session, 
                        manual_info
                    )
                    
                    # Detect platform
                    platform = ProductScraper.detect_platform(clean_url)
                    
                    # Format output
                    output = DealFormatter.format_deal(product_info, clean_url, platform)
                    
                    # Send response safely
                    await safe_send_message(update, context, output, disable_web_page_preview=True, parse_mode=ParseMode.HTML)
                    
                    # Small delay between processing multiple links
                    if len(links) > 1:
                        await asyncio.sleep(0.5)
                    
                except Exception as e:
                    logger.error(f"Error processing link {url}: {str(e)}")
                    # Try to send error message safely
                    error_msg = f"❌ Error processing link\n\n{url}\n\n@reviewcheckk"
                    await safe_send_message(update, context, error_msg, disable_web_page_preview=True)
                    continue
                    
        except Exception as e:
            logger.error(f"Error in process_message: {str(e)}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    msg = (
        "🤖 Deal Bot Active!\n\n"
        "✅ Smart link detection\n"
        "✅ Automatic unshortening\n"
        "✅ Clean affiliate removal\n"
        "✅ Price & title extraction\n"
        "✅ Meesho size & PIN support\n\n"
        "Send any product link and I'll format it perfectly!\n"
        "Supports: Amazon, Flipkart, Meesho, Myntra, Ajio & more\n\n"
        "@reviewcheckk"
    )
    await safe_send_message(update, context, msg)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")

async def safe_send_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, **kwargs):
    """Safely send message with error handling"""
    try:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            **kwargs
        )
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        # Try sending a simple error message
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Sorry, failed to process this request."
            )
        except:
            pass

def main():
    """Main function to run the bot"""
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Initialize bot handler
    bot = DealBot()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(
        filters.TEXT | filters.CAPTION, 
        bot.process_message
    ))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start bot
    print(f"✅ Bot @{BOT_USERNAME} is starting...")
    print("📡 Ready to process messages from Groups, Channels, and DMs")
    print("🔗 Monitoring for product links 24/7")
    
    # Run the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
