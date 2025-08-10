import logging
import re
import asyncio
import aiohttp
from typing import Optional, Dict, List, Tuple
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from telegram import Update, Message
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot Configuration
BOT_TOKEN = "8465346144:AAGSHC77UkXVZZTUscbYItvJxgQbBxmFcWo"
BOT_USERNAME = "@tg_workbot"

# Supported URL shorteners
SHORTENERS = [
    'cutt.ly', 'spoo.me', 'amzn-to.co', 'fkrt.cc', 
    'bitli.in', 'da.gd', 'wishlink.com', 'bit.ly',
    'tinyurl.com', 'short.link', 'ow.ly', 'is.gd'
]

# Gender keywords
GENDER_KEYWORDS = {
    'men': ['men', "men's", 'male', 'boy', 'boys', 'gents'],
    'women': ['women', "women's", 'female', 'girl', 'girls', 'ladies', 'lady'],
    'kids': ['kids', 'children', 'child', 'baby', 'infant', 'toddler'],
    'unisex': ['unisex', 'universal']
}

# Quantity keywords
QUANTITY_KEYWORDS = [
    'pack of', 'set of', 'pcs', 'pieces', 'kg', 'gram', 'g',
    'ml', 'litre', 'liter', 'l', 'combo', 'pair'
]

# Size patterns
SIZE_PATTERNS = ['S', 'M', 'L', 'XL', 'XXL', 'XXXL', '2XL', '3XL', '4XL', '5XL']

class LinkProcessor:
    """Handles link detection, unshortening, and cleaning"""
    
    @staticmethod
    def extract_links(text: str) -> List[str]:
        """Extract all URLs from text"""
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        return re.findall(url_pattern, text) if text else []
    
    @staticmethod
    def is_shortened_url(url: str) -> bool:
        """Check if URL is from a shortener service"""
        domain = urlparse(url).netloc.lower()
        return any(shortener in domain for shortener in SHORTENERS)
    
    @staticmethod
    async def unshorten_url(url: str, session: aiohttp.ClientSession) -> str:
        """Resolve shortened URL to full URL"""
        try:
            async with session.head(url, allow_redirects=True, timeout=10) as response:
                return str(response.url)
        except:
            try:
                async with session.get(url, allow_redirects=True, timeout=10) as response:
                    return str(response.url)
            except:
                return url
    
    @staticmethod
    def clean_affiliate_url(url: str) -> str:
        """Remove affiliate tags from URL"""
        parsed = urlparse(url)
        
        # Amazon affiliate cleaning
        if 'amazon' in parsed.netloc or 'amzn' in parsed.netloc:
            query_params = parse_qs(parsed.query)
            # Remove affiliate parameters
            affiliate_params = ['tag', 'ref', 'linkCode', 'linkId', 'psc']
            for param in affiliate_params:
                query_params.pop(param, None)
            
            # Keep only essential parameters
            clean_query = urlencode({k: v[0] for k, v in query_params.items()}, doseq=False)
            return urlunparse(parsed._replace(query=clean_query))
        
        # Flipkart affiliate cleaning
        elif 'flipkart' in parsed.netloc:
            query_params = parse_qs(parsed.query)
            affiliate_params = ['affid', 'affExtParam1', 'affExtParam2']
            for param in affiliate_params:
                query_params.pop(param, None)
            clean_query = urlencode({k: v[0] for k, v in query_params.items()}, doseq=False)
            return urlunparse(parsed._replace(query=clean_query))
        
        # Meesho cleaning
        elif 'meesho' in parsed.netloc:
            # Meesho URLs are usually clean, just return base product URL
            return url.split('?')[0]
        
        return url

class ProductScraper:
    """Scrapes product information from URLs"""
    
    @staticmethod
    async def scrape_product(url: str, session: aiohttp.ClientSession) -> Dict:
        """Scrape product details from URL"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            async with session.get(url, headers=headers, timeout=15) as response:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                product_info = {
                    'title': '',
                    'price': '',
                    'sizes': [],
                    'pin': '',
                    'gender': '',
                    'quantity': ''
                }
                
                # Extract title
                title = ProductScraper._extract_title(soup)
                product_info['title'] = ProductScraper._clean_title(title)
                
                # Extract price
                product_info['price'] = ProductScraper._extract_price(soup, html)
                
                # Extract sizes
                product_info['sizes'] = ProductScraper._extract_sizes(soup, html)
                
                # Extract pin code (for Meesho)
                if 'meesho' in url.lower():
                    product_info['pin'] = ProductScraper._extract_pin(soup, html)
                
                # Detect gender and quantity from title
                product_info['gender'] = ProductScraper._detect_gender(product_info['title'])
                product_info['quantity'] = ProductScraper._detect_quantity(product_info['title'])
                
                return product_info
                
        except Exception as e:
            logger.error(f"Error scraping {url}: {str(e)}")
            return {}
    
    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str:
        """Extract product title"""
        # Try multiple selectors
        selectors = [
            'h1',
            'meta[property="og:title"]',
            'meta[name="twitter:title"]',
            'title'
        ]
        
        for selector in selectors:
            element = soup.select_one(selector)
            if element:
                if selector.startswith('meta'):
                    return element.get('content', '')
                else:
                    return element.get_text(strip=True)
        return ''
    
    @staticmethod
    def _clean_title(title: str) -> str:
        """Clean and shorten title"""
        # Remove common unnecessary words
        remove_words = ['Buy', 'Shop', 'Online', 'India', 'Best', 'Price', 'Sale', 
                       'Discount', 'Offer', 'Deal', 'Exclusive', 'Limited']
        
        for word in remove_words:
            title = re.sub(rf'\b{word}\b', '', title, flags=re.IGNORECASE)
        
        # Remove extra spaces and limit length
        title = ' '.join(title.split())
        
        # Limit to first 50 characters if too long
        if len(title) > 50:
            title = title[:50].rsplit(' ', 1)[0] + '...'
        
        return title
    
    @staticmethod
    def _extract_price(soup: BeautifulSoup, html: str) -> str:
        """Extract product price"""
        # Pattern to find price
        price_pattern = r'[₹Rs\.]\s*[\d,]+(?:\.\d{2})?'
        prices = re.findall(price_pattern, html)
        
        if prices:
            # Clean and return first price found
            price = re.sub(r'[^\d]', '', prices[0])
            return price
        
        # Try specific selectors
        selectors = [
            '.price', '.product-price', '.selling-price',
            '[class*="price"]', '[class*="Price"]'
        ]
        
        for selector in selectors:
            element = soup.select_one(selector)
            if element:
                text = element.get_text()
                price = re.sub(r'[^\d]', '', text)
                if price:
                    return price
        
        return ''
    
    @staticmethod
    def _extract_sizes(soup: BeautifulSoup, html: str) -> List[str]:
        """Extract available sizes"""
        sizes = []
        
        # Look for size elements
        size_elements = soup.find_all(['span', 'div', 'button'], 
                                     text=re.compile(r'\b(' + '|'.join(SIZE_PATTERNS) + r')\b'))
        
        for element in size_elements:
            size = element.get_text(strip=True)
            if size in SIZE_PATTERNS and size not in sizes:
                sizes.append(size)
        
        return sizes
    
    @staticmethod
    def _extract_pin(soup: BeautifulSoup, html: str) -> str:
        """Extract pin code from page"""
        # Pattern for 6-digit pin code
        pin_pattern = r'\b\d{6}\b'
        pins = re.findall(pin_pattern, html)
        
        # Return first valid pin found
        for pin in pins:
            if pin.startswith(('1', '2', '3', '4', '5', '6', '7', '8', '9')):
                return pin
        
        return '110001'  # Default pin
    
    @staticmethod
    def _detect_gender(title: str) -> str:
        """Detect gender from title"""
        title_lower = title.lower()
        
        for gender, keywords in GENDER_KEYWORDS.items():
            for keyword in keywords:
                if keyword in title_lower:
                    return gender.capitalize()
        
        return ''
    
    @staticmethod
    def _detect_quantity(title: str) -> str:
        """Detect quantity from title"""
        title_lower = title.lower()
        
        for keyword in QUANTITY_KEYWORDS:
            pattern = rf'{keyword}\s*\d+'
            match = re.search(pattern, title_lower, re.IGNORECASE)
            if match:
                return match.group(0).title()
        
        return ''

class DealBot:
    """Main bot handler"""
    
    def __init__(self):
        self.session = None
    
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
        message = update.message or update.channel_post
        if not message:
            return
        
        await self.initialize()
        
        # Extract text and caption
        text = message.text or message.caption or ''
        
        # Extract links
        links = LinkProcessor.extract_links(text)
        
        if not links:
            return
        
        # Process first link found
        url = links[0]
        
        try:
            # Check if shortened and unshorten
            if LinkProcessor.is_shortened_url(url):
                url = await LinkProcessor.unshorten_url(url, self.session)
            
            # Clean affiliate tags
            clean_url = LinkProcessor.clean_affiliate_url(url)
            
            # Scrape product info
            product_info = await ProductScraper.scrape_product(clean_url, self.session)
            
            # Check if we have image caption for title
            if message.caption and not product_info.get('title'):
                product_info['title'] = ProductScraper._clean_title(message.caption)
            
            # Format output
            output = self.format_output(product_info, clean_url)
            
            # Send response
            await message.reply_text(output, disable_web_page_preview=True)
            
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
    
    def format_output(self, product_info: Dict, url: str) -> str:
        """Format product information for output"""
        parts = []
        
        # Title line with gender and quantity
        title_parts = []
        if product_info.get('gender'):
            title_parts.append(product_info['gender'])
        if product_info.get('quantity'):
            title_parts.append(product_info['quantity'])
        if product_info.get('title'):
            title_parts.append(product_info['title'])
        
        if product_info.get('price'):
            title_parts.append(f"@{product_info['price']} rs")
        
        if title_parts:
            parts.append(' '.join(title_parts))
        
        # URL
        parts.append(url)
        parts.append('')  # Empty line
        
        # Sizes
        if product_info.get('sizes'):
            if len(product_info['sizes']) >= len(SIZE_PATTERNS) - 2:
                parts.append('Size - All')
            else:
                parts.append(f"Size - {', '.join(product_info['sizes'])}")
        
        # Pin (for Meesho)
        if 'meesho' in url.lower():
            pin = product_info.get('pin', '110001')
            parts.append(f"Pin - {pin}")
        
        # Footer
        parts.append('')
        parts.append('@reviewcheckk')
        
        return '\n'.join(parts)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    await update.message.reply_text(
        "🤖 Deal Bot Active!\n\n"
        "Send me any product link and I'll extract the deal information.\n"
        "Works with shortened links too!\n\n"
        "Supported: Amazon, Flipkart, Meesho, and more!"
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")

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
