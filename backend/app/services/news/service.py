"""News aggregation and sentiment analysis service."""
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import asyncio
import aiohttp
from bs4 import BeautifulSoup
import feedparser
from dataclasses import dataclass
from enum import Enum

class Sentiment(Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    
@dataclass
class NewsItem:
    title: str
    summary: str
    source: str
    url: str
    published: datetime
    sentiment: Sentiment
    impact_score: float
    symbols: List[str]
    
class NewsService:
    """Aggregates news from multiple sources with sentiment analysis."""
    
    SOURCES = {
        "moneycontrol": "https://www.moneycontrol.com/rss/latestnews.xml",
        "economictimes": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "reuters": "https://feeds.reuters.com/reuters/INmarketNews",
        "bloomberg": "https://feeds.bloomberg.com/markets/news.rss",
    }
    
    def __init__(self):
        self.session = None
        self._cache = {}
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()
            
    async def fetch_news(self, symbols: List[str] = None) -> List[NewsItem]:
        """Fetch news for given symbols or general market news."""
        tasks = [self._fetch_feed(source, url) for source, url in self.SOURCES.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_news = []
        for items in results:
            if isinstance(items, list):
                all_news.extend(items)
                
        # Filter by symbols if provided
        if symbols:
            all_news = [n for n in all_news if any(s in n.symbols for s in symbols)]
            
        # Sort by published date
        all_news.sort(key=lambda x: x.published, reverse=True)
        return all_news[:100]  # Return top 100
        
    async def _fetch_feed(self, source: str, url: str) -> List[NewsItem]:
        """Fetch and parse RSS feed."""
        try:
            async with self.session.get(url, timeout=10) as resp:
                content = await resp.text()
                feed = feedparser.parse(content)
                
                items = []
                for entry in feed.entries[:20]:
                    item = NewsItem(
                        title=entry.get('title', ''),
                        summary=entry.get('summary', '')[:500],
                        source=source,
                        url=entry.get('link', ''),
                        published=self._parse_date(entry.get('published')),
                        sentiment=self._analyze_sentiment(entry.get('title', '') + ' ' + entry.get('summary', '')),
                        impact_score=self._calculate_impact(entry),
                        symbols=self._extract_symbols(entry.get('title', '') + ' ' + entry.get('summary', ''))
                    )
                    items.append(item)
                return items
        except Exception as e:
            print(f"Error fetching {source}: {e}")
            return []
            
    def _analyze_sentiment(self, text: str) -> Sentiment:
        """Simple keyword-based sentiment analysis."""
        text_lower = text.lower()
        
        positive_words = ['surge', 'gain', 'profit', 'bullish', 'growth', 'rise', 'jump', 
                         'outperform', 'upgrade', 'record', 'strong', 'beat']
        negative_words = ['fall', 'loss', 'bearish', 'decline', 'drop', 'crash', 'weak',
                         'downgrade', 'miss', 'concern', 'risk', 'sell']
        
        pos_count = sum(1 for word in positive_words if word in text_lower)
        neg_count = sum(1 for word in negative_words if word in text_lower)
        
        if pos_count > neg_count:
            return Sentiment.POSITIVE
        elif neg_count > pos_count:
            return Sentiment.NEGATIVE
        return Sentiment.NEUTRAL
        
    def _calculate_impact(self, entry: dict) -> float:
        """Calculate potential market impact score (0-1)."""
        keywords = ['earnings', 'merger', 'acquisition', 'bankruptcy', 'fraud', 
                   'sec', 'investigation', 'ipo', 'dividend', 'buyback']
        text = (entry.get('title', '') + ' ' + entry.get('summary', '')).lower()
        
        score = sum(0.1 for kw in keywords if kw in text)
        return min(score, 1.0)
        
    def _extract_symbols(self, text: str) -> List[str]:
        """Extract stock symbols from text."""
        import re
        # Simple pattern for Indian stocks
        nse_pattern = r'\b[A-Z]{3,15}\b'
        matches = re.findall(nse_pattern, text)
        
        # Filter common words
        common_words = {'THE', 'AND', 'FOR', 'WITH', 'FROM', 'INTO', 'NYSE', 'NSE', 'BSE'}
        symbols = [m for m in matches if m not in common_words and len(m) >= 3]
        return symbols[:5]  # Limit to 5 symbols
        
    def _parse_date(self, date_str: str) -> datetime:
        """Parse various date formats."""
        if not date_str:
            return datetime.now()
        try:
            from dateutil import parser
            return parser.parse(date_str)
        except:
            return datetime.now()