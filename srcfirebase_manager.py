"""
Firebase Manager for Project Ivy
Handles all Firestore operations with proper error handling and connection management.
"""
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from contextlib import contextmanager

import firebase_admin
from firebase_admin import credentials, firestore, exceptions
from google.cloud.firestore_v1 import DocumentReference, CollectionReference

from config import config

# Initialize logger
logger = logging.getLogger(__name__)

class FirebaseManager:
    """
    Manages Firebase Firestore connections and operations with:
    - Connection pooling and reuse
    - Automatic retry on transient failures
    - Comprehensive error handling
    - Type-safe document operations
    """
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FirebaseManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._initialize_firebase()
            self._initialized = True
    
    def _initialize_firebase(self) -> None:
        """Initialize Firebase Admin SDK with error handling"""
        try:
            # Check if Firebase app already exists
            if not firebase_admin._apps:
                # Create credentials from config
                cred_dict = {
                    "type": "service_account",
                    "project_id": config.firebase.project_id,
                    "private_key_id": config.firebase.private_key_id,
                    "private_key": config.firebase.private_key,
                    "client_email": config.firebase.client_email,
                    "client_id": config.firebase.client_id,
                    "token_uri": config.firebase.token_uri,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{config.firebase.client_email}"
                }
                
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
                logger.info("Firebase Admin SDK initialized successfully")
            else:
                logger.info("Firebase Admin SDK already initialized")
            
            self.db = firestore.client()
            
        except ValueError as e:
            logger.error(f"Firebase initialization failed - invalid credentials: {e}")
            raise
        except exceptions.FirebaseError as e:
            logger.error(f"Firebase initialization failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during Firebase initialization: {e}")
            raise
    
    @contextmanager
    def transaction(self, max_attempts: int = 3):
        """
        Context manager for Firestore transactions with retry logic
        
        Args:
            max_attempts: Maximum number of retry attempts
        """
        attempt = 0
        while attempt < max_attempts:
            try:
                transaction = self.db.transaction()
                yield transaction
                return
            except exceptions.FirebaseError as e:
                attempt += 1
                if attempt == max_attempts:
                    logger.error(f"Transaction failed after {max_attempts} attempts: {e}")
                    raise
                logger.warning(f"Transaction attempt {attempt} failed, retrying: {e}")
    
    # User Management Operations
    def create_user(self, user_id: str, user_data: Dict[str, Any]) -> bool:
        """
        Create a new user document with validation
        
        Args:
            user_id: Firebase Auth UID
            user_data: User profile data
            
        Returns:
            True if successful, False otherwise
        """
        try:
            user_ref = self.db.collection('users').document(user_id)
            
            # Add metadata
            user_data['created_at'] = firestore.SERVER_TIMESTAMP
            user_data['updated_at'] = firestore.SERVER_TIMESTAMP
            user_data['is_active'] = True
            user_data['tier'] = 'free'  # Default tier
            
            user_ref.set(user_data)
            logger.info(f"Created user document for {user_id}")
            return True
            
        except exceptions.FirebaseError as e:
            logger.error(f"Failed to create user {user_id}: {e}")
            return False
    
    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve user document with error handling"""
        try:
            user_ref = self.db.collection('users').document(user_id)
            doc = user_ref.get()
            
            if doc.exists:
                return doc.to_dict()
            else:
                logger.warning(f"User {user_id} not found")
                return None
                
        except exceptions.FirebaseError as e:
            logger.error(f"Failed to retrieve user {user_id}: {e}")
            return None
    
    # Portfolio Management Operations
    def add_portfolio(self, user_id: str, portfolio_data: Dict[str, Any]) -> Optional[str]:
        """
        Add a portfolio for a user with tier validation
        
        Args:
            user_id: Firebase Auth UID
            portfolio_data: Portfolio configuration
            
        Returns:
            Portfolio ID if successful, None otherwise
        """
        try:
            user = self.get_user(user_id)
            if not user:
                return None
            
            # Check portfolio limits based on tier
            portfolios = self.get_user_portfolios(user_id)
            tier = user.get('tier', 'free')
            max_portfolios = config.alert.max_portfolios_free if tier == 'free' else config.alert.max_portfolios_pro
            
            if len(portfolios) >= max_portfolios:
                logger.warning(f"User {user_id} at portfolio limit for tier {tier}")
                return None
            
            # Add portfolio to subcollection
            portfolio_ref = self.db.collection('users').document(user_id).collection('portfolios').document()
            
            # Add metadata
            portfolio_data['created_at'] = firestore.SERVER_TIMESTAMP
            portfolio_data['updated_at'] = firestore.SERVER_TIMESTAMP
            portfolio_data['is_active'] = True
            portfolio_data['last_scan'] = None
            
            portfolio_ref.set(portfolio_data)
            logger.info(f"Added portfolio {portfolio_ref.id} for user {user_id}")
            return portfolio_ref.id
            
        except exceptions.FirebaseError as e:
            logger.error(f"Failed to add portfolio for user {user_id}: {e}")
            return None
    
    def get_user_portfolios(self, user_id: str) -> List[Dict[str, Any]]:
        """Retrieve all portfolios for a user"""
        try:
            portfolios_ref = self.db.collection('users').document(user_id).collection('portfolios')
            docs = portfolios_ref.where('is_active', '==', True).stream()
            
            portfolios = []
            for doc in docs:
                portfolio_data = doc.to_dict()
                portfolio_data['id'] = doc.id
                portfolios.append(portfolio_data)
            
            return portfolios
            
        except exceptions.FirebaseError as e:
            logger.error(f"Failed to retrieve portfolios for user {user_id}: {e}")
            return []
    
    # Alert Management Operations
    def log_alert(self, user_id: str, alert_data: Dict[str, Any]) -> bool:
        """
        Log an alert to Firestore with cooldown checking
        
        Args:
            user_id: Target user ID
            alert_data: Alert payload
            
        Returns:
            True if alert was logged, False if cooldown active
        """
        try:
            # Check cooldown
            cooldown_cutoff = datetime.utcnow() - timedelta(seconds=config.alert.cooldown_seconds)
            
            alerts_ref = self.db.collection('users').document(user_id).collection('alerts')
            recent_alerts = alerts_ref.where('created_at', '>=', cooldown_cutoff).limit(1).stream()
            
            if list(recent_alerts):
                logger.info(f"Alert cooldown active for user {user_id}")
                return False
            
            # Log alert
            alert_ref = alerts_ref.document()
            alert_data['created_at'] = firestore.SERVER_TIMESTAMP
            alert_data['delivered'] = False
            alert_data['read'] = False
            
            alert_ref.set(alert_data)
            logger.info(f"Logged alert {alert_ref.id} for user {user_id}")
            return True
            
        except exceptions.FirebaseError as e:
            logger.error(f"Failed to log alert for user {user_id}: {e}")
            return False
    
    # State Management Operations
    def update_agent_state(self, agent_id: str, state_data: Dict[str, Any]) -> bool:
        """
        Update or create agent state document
        
        Args:
            agent_id: Unique agent identifier
            state_data: State information
            
        Returns:
            True if successful
        """
        try:
            state_ref = self.db.collection('agent_states').document(agent_id)
            
            state_data['last_updated'] = firestore.SERVER_TIMESTAMP
            state_data['agent_id'] = agent_id
            
            state_ref.set(state_data, merge=True)
            return True
            
        except exceptions.FirebaseError as e:
            logger.error(f"Failed to update agent state {agent_id}: {e}")
            return False
    
    def get_agent_state(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve agent state"""
        try:
            state_ref = self.db.collection('agent_states').document(agent_id)
            doc = state_ref.get()
            
            if doc.exists:
                return doc.to_dict()
            return None
            
        except exceptions.FirebaseError as e:
            logger.error(f"Failed to retrieve agent state {agent_id}: {e}")
            return None
    
    # Bulk Operations with Error Recovery
    def batch_update(self, updates: List[tuple]) -> int:
        """
        Execute batch updates with error recovery
        
        Args:
            updates: List of (collection, document_id, data) tuples
            
        Returns:
            Number of successful updates
        """
        if not updates:
            return 0
        
        batch = self.db.batch()
        successful = 0
        
        for collection, doc_id, data in updates:
            try:
                doc_ref = self.db.col