"""
Project Ivy Configuration Manager
Handles environment variables, constants, and runtime configuration with validation.
"""
import os
from typing import Optional, Dict, Any
from dataclasses import dataclass
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

@dataclass
class FirebaseConfig:
    """Firebase configuration with validation"""
    project_id: str
    private_key_id: str
    private_key: str
    client_email: str
    client_id: str
    token_uri: str
    
    @classmethod
    def from_env(cls) -> 'FirebaseConfig':
        """Load Firebase config from environment with validation"""
        private_key = os.getenv('FIREBASE_PRIVATE_KEY', '').replace('\\n', '\n')
        
        if not private_key.startswith('-----BEGIN PRIVATE KEY-----'):
            logging.warning("Firebase private key may be malformed")
        
        return cls(
            project_id=os.getenv('FIREBASE_PROJECT_ID', ''),
            private_key_id=os.getenv('FIREBASE_PRIVATE_KEY_ID', ''),
            private_key=private_key,
            client_email=os.getenv('FIREBASE_CLIENT_EMAIL', ''),
            client_id=os.getenv('FIREBASE_CLIENT_ID', ''),
            token_uri=os.getenv('FIREBASE_TOKEN_URI', 'https://oauth2.googleapis.com/token')
        )
    
    def validate(self) -> bool:
        """Validate Firebase configuration"""
        required_fields = ['project_id', 'private_key', 'client_email']
        return all(getattr(self, field) for field in required_fields)

@dataclass
class ExchangeConfig:
    """Exchange API configuration"""
    binance_api_key: Optional[str] = None
    binance_secret: Optional[str] = None
    coinbase_api_key: Optional[str] = None
    coinbase_secret: Optional[str] = None
    
    @classmethod
    def from_env(cls) -> 'ExchangeConfig':
        """Load exchange config from environment"""
        return cls(
            binance_api_key=os.getenv('BINANCE_API_KEY'),
            binance_secret=os.getenv('BINANCE_SECRET'),
            coinbase_api_key=os.getenv('COINBASE_API_KEY'),
            coinbase_secret=os.getenv('COINBASE_SECRET')
        )

@dataclass
class AlertConfig:
    """Alert system configuration"""
    cooldown_seconds: int
    max_portfolios_free: int
    max_portfolios_pro: int
    crisis_alert_threshold: int
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    
    @classmethod
    def from_env(cls) -> 'AlertConfig':
        """Load alert config from environment"""
        return cls(
            cooldown_seconds=int(os.getenv('ALERT_COOLDOWN_SECONDS', '300')),
            max_portfolios_free=int(os.getenv('MAX_PORTFOLIOS_FREE', '3')),
            max_portfolios_pro=int(os.getenv('MAX_PORTFOLIOS_PRO', '20')),
            crisis_alert_threshold=int(os.getenv('CRISIS_ALERT_THRESHOLD', '1000')),
            telegram_bot_token=os.getenv('TELEGRAM_BOT_TOKEN'),
            telegram_chat_id=os.getenv('TELEGRAM_CHAT_ID')
        )

class Config:
    """Main configuration manager"""
    def __init__(self):
        self.firebase = FirebaseConfig.from_env()
        self.exchange = ExchangeConfig.from_env()
        self.alert = AlertConfig.from_env()
        self._validate()
    
    def _validate(self) -> None:
        """Validate all configurations"""
        if not self.firebase.validate():
            logging.error("Firebase configuration incomplete. Check environment variables.")
            raise ValueError("Firebase configuration invalid")
        
        # Warn if exchange keys are missing (free tier will be rate-limited)
        if not self.exchange.binance_api_key or not self.exchange.binance_secret:
            logging.warning("Binance API keys not found. Data collection will be rate-limited.")
        
        # Warn if Telegram bot token is missing
        if not self.alert.telegram_bot_token:
            logging.warning("Telegram bot token not found. Alert delivery will be limited.")

# Global configuration instance
config = Config()