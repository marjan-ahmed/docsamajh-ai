"""
Authentication and User Management Module
Handles user registration, login, session management, and data isolation
Supports both username/password and Google OAuth authentication
"""

import hashlib
import sqlite3
import os
from datetime import datetime
from typing import Optional, Dict, List
import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.auth.transport import requests
from urllib.parse import urlencode
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
ENV = os.getenv("ENV", "local")  # default is local

# Set redirect URI based on environment
if ENV == "production":
    REDIRECT_URI = "https://docsamajh-ai.streamlit.app"
else:
    REDIRECT_URI = "http://localhost:8501"

# Database setup
DB_PATH = "docsamajh_users.db"

# Google OAuth Configuration
GOOGLE_CLIENT_ID = os.getenv("CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("CLIENT_SECRET")

# GitHub OAuth Configuration
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")

# OAuth scopes
GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile"
]

GITHUB_SCOPES = ["read:user", "user:email"]

def init_database():
    """Initialize SQLite database for user management"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            full_name TEXT,
            company TEXT,
            google_id TEXT UNIQUE,
            github_id TEXT UNIQUE,
            profile_picture TEXT,
            auth_provider TEXT DEFAULT 'local',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        )
    """)
    
    # User sessions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_sessions (
            session_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            session_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            session_end TIMESTAMP,
            documents_processed INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)
    
    # Audit trail table (per user)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_trail (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            session_id INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            action TEXT NOT NULL,
            file_name TEXT,
            doc_type TEXT,
            status TEXT,
            details TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (session_id) REFERENCES user_sessions(session_id)
        )
    """)
    
    # Processed documents table (per user)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_documents (
            doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            session_id INTEGER,
            file_name TEXT NOT NULL,
            doc_type TEXT NOT NULL,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            extracted_data TEXT,
            metadata TEXT,
            status TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (session_id) REFERENCES user_sessions(session_id)
        )
    """)
    
    # User statistics table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_stats (
            stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            total_processed INTEGER DEFAULT 0,
            total_matched INTEGER DEFAULT 0,
            total_flagged INTEGER DEFAULT 0,
            total_invoices INTEGER DEFAULT 0,
            total_pos INTEGER DEFAULT 0,
            total_statements INTEGER DEFAULT 0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)
    
    # Reconciliation history table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reconciliation_history (
            recon_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            session_id INTEGER,
            invoice_file TEXT,
            po_file TEXT,
            reconciled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            risk_level TEXT,
            matched BOOLEAN,
            variance_amount REAL,
            variance_percentage REAL,
            discrepancies TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (session_id) REFERENCES user_sessions(session_id)
        )
    """)
    
    conn.commit()
    conn.close()

def hash_password(password: str) -> str:
    """Hash password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def create_user(username: str, email: str, password: str, full_name: str = "", 
                company: str = "", google_id: str = None, github_id: str = None,
                profile_picture: str = None, auth_provider: str = "local") -> bool:
    """Create a new user account"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        password_hash = hash_password(password) if password else None
        
        cursor.execute("""
            INSERT INTO users (username, email, password_hash, full_name, company, 
                             google_id, github_id, profile_picture, auth_provider)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (username, email, password_hash, full_name, company, google_id, 
              github_id, profile_picture, auth_provider))
        
        user_id = cursor.lastrowid
        
        # Initialize user stats
        cursor.execute("""
            INSERT INTO user_stats (user_id)
            VALUES (?)
        """, (user_id,))
        
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        return False
    except Exception as e:
        print(f"Error creating user: {e}")
        return False

def authenticate_user(username: str, password: str) -> Optional[Dict]:
    """Authenticate user and return user data"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        password_hash = hash_password(password)
        
        cursor.execute("""
            SELECT user_id, username, email, full_name, company, created_at, is_active, 
                   profile_picture, auth_provider
            FROM users
            WHERE username = ? AND password_hash = ? AND is_active = 1
        """, (username, password_hash))
        
        user = cursor.fetchone()
        
        if user:
            # Update last login
            cursor.execute("""
                UPDATE users
                SET last_login = ?
                WHERE user_id = ?
            """, (datetime.now(), user[0]))
            conn.commit()
            
            user_data = {
                "user_id": user[0],
                "username": user[1],
                "email": user[2],
                "full_name": user[3],
                "company": user[4],
                "created_at": user[5],
                "is_active": user[6],
                "profile_picture": user[7],
                "auth_provider": user[8]
            }
            
            conn.close()
            return user_data
        
        conn.close()
        return None
    except Exception as e:
        print(f"Authentication error: {e}")
        return None

def authenticate_google_user(google_id: str, email: str, name: str, picture: str) -> Optional[Dict]:
    """Authenticate or create user via Google OAuth"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check if user exists with this Google ID
        cursor.execute("""
            SELECT user_id, username, email, full_name, company, created_at, is_active,
                   profile_picture, auth_provider
            FROM users
            WHERE google_id = ? AND is_active = 1
        """, (google_id,))
        
        user = cursor.fetchone()
        
        if user:
            # Update last login and profile picture
            cursor.execute("""
                UPDATE users
                SET last_login = ?, profile_picture = ?
                WHERE user_id = ?
            """, (datetime.now(), picture, user[0]))
            conn.commit()
            
            user_data = {
                "user_id": user[0],
                "username": user[1],
                "email": user[2],
                "full_name": user[3],
                "company": user[4],
                "created_at": user[5],
                "is_active": user[6],
                "profile_picture": user[7],
                "auth_provider": user[8]
            }
            conn.close()
            return user_data
        else:
            # Check if email already exists (link accounts)
            cursor.execute("""
                SELECT user_id FROM users WHERE email = ?
            """, (email,))
            existing = cursor.fetchone()
            
            if existing:
                # Link Google account to existing user
                cursor.execute("""
                    UPDATE users
                    SET google_id = ?, profile_picture = ?, last_login = ?
                    WHERE user_id = ?
                """, (google_id, picture, datetime.now(), existing[0]))
                conn.commit()
                conn.close()
                
                # Return updated user data
                return authenticate_google_user(google_id, email, name, picture)
            else:
                # Create new user
                username = email.split('@')[0]
                # Make username unique if needed
                base_username = username
                counter = 1
                while True:
                    cursor.execute("SELECT user_id FROM users WHERE username = ?", (username,))
                    if not cursor.fetchone():
                        break
                    username = f"{base_username}{counter}"
                    counter += 1
                
                cursor.execute("""
                    INSERT INTO users (username, email, full_name, google_id, 
                                     profile_picture, auth_provider, password_hash)
                    VALUES (?, ?, ?, ?, ?, 'google', NULL)
                """, (username, email, name, google_id, picture))
                
                user_id = cursor.lastrowid
                
                # Initialize user stats
                cursor.execute("""
                    INSERT INTO user_stats (user_id)
                    VALUES (?)
                """, (user_id,))
                
                # Update last login
                cursor.execute("""
                    UPDATE users SET last_login = ? WHERE user_id = ?
                """, (datetime.now(), user_id))
                
                conn.commit()
                conn.close()
                
                # Return new user data
                return authenticate_google_user(google_id, email, name, picture)
        
    except Exception as e:
        print(f"Google authentication error: {e}")
        return None

def verify_google_token(token: str) -> Optional[Dict]:
    """Verify Google ID token and return user info"""
    try:
        idinfo = id_token.verify_oauth2_token(
            token, 
            requests.Request(), 
            GOOGLE_CLIENT_ID
        )
        
        if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
            return None
        
        return {
            'google_id': idinfo['sub'],
            'email': idinfo['email'],
            'name': idinfo.get('name', ''),
            'picture': idinfo.get('picture', '')
        }
    except Exception as e:
        print(f"Token verification error: {e}")
        return None

def authenticate_github_user(github_id: str, email: str, name: str, username: str, picture: str) -> Optional[Dict]:
    """Authenticate or create user via GitHub OAuth"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check if user exists with this GitHub ID
        cursor.execute("""
            SELECT user_id, username, email, full_name, company, created_at, is_active,
                   profile_picture, auth_provider
            FROM users
            WHERE github_id = ? AND is_active = 1
        """, (github_id,))
        
        user = cursor.fetchone()
        
        if user:
            # Update last login and profile picture
            cursor.execute("""
                UPDATE users
                SET last_login = ?, profile_picture = ?
                WHERE user_id = ?
            """, (datetime.now(), picture, user[0]))
            conn.commit()
            
            user_data = {
                "user_id": user[0],
                "username": user[1],
                "email": user[2],
                "full_name": user[3],
                "company": user[4],
                "created_at": user[5],
                "is_active": user[6],
                "profile_picture": user[7],
                "auth_provider": user[8]
            }
            conn.close()
            return user_data
        else:
            # Check if email already exists (link accounts)
            if email:
                cursor.execute("""
                    SELECT user_id FROM users WHERE email = ?
                """, (email,))
                existing = cursor.fetchone()
                
                if existing:
                    # Link GitHub account to existing user
                    cursor.execute("""
                        UPDATE users
                        SET github_id = ?, profile_picture = ?, last_login = ?
                        WHERE user_id = ?
                    """, (github_id, picture, datetime.now(), existing[0]))
                    conn.commit()
                    conn.close()
                    return authenticate_github_user(github_id, email, name, username, picture)
            
            # Create new user
            final_username = username or (email.split('@')[0] if email else f"user{github_id[:8]}")
            base_username = final_username
            counter = 1
            while True:
                cursor.execute("SELECT user_id FROM users WHERE username = ?", (final_username,))
                if not cursor.fetchone():
                    break
                final_username = f"{base_username}{counter}"
                counter += 1
            
            cursor.execute("""
                INSERT INTO users (username, email, full_name, github_id, 
                                 profile_picture, auth_provider, password_hash)
                VALUES (?, ?, ?, ?, ?, 'github', NULL)
            """, (final_username, email or f"{github_id}@github.users.noreply.com", 
                  name, github_id, picture))
            
            user_id = cursor.lastrowid
            
            # Initialize user stats
            cursor.execute("""
                INSERT INTO user_stats (user_id)
                VALUES (?)
            """, (user_id,))
            
            # Update last login
            cursor.execute("""
                UPDATE users SET last_login = ? WHERE user_id = ?
            """, (datetime.now(), user_id))
            
            conn.commit()
            conn.close()
            
            # Return new user data
            return authenticate_github_user(github_id, email, name, username, picture)
        
    except Exception as e:
        print(f"GitHub authentication error: {e}")
        return None

def get_google_auth_url() -> str:
    """Generate Google OAuth authorization URL"""
    try:
        # Create client config
        client_config = {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [REDIRECT_URI]
            }
        }
        
        flow = Flow.from_client_config(
            client_config,
            scopes=GOOGLE_SCOPES,
            redirect_uri=REDIRECT_URI
        )
        
        auth_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent',
            state='google'  # Identify Google OAuth flow
        )
        
        return auth_url
    except Exception as e:
        print(f"Error generating Google auth URL: {e}")
        return ""

def exchange_google_code(code: str) -> Optional[Dict]:
    """Exchange Google authorization code for access token and get user info"""
    try:
        import requests as http_requests
        
        # Exchange authorization code for access token
        token_url = "https://oauth2.googleapis.com/token"
        token_data = {
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code"
        }
        
        token_response = http_requests.post(token_url, data=token_data)
        
        if token_response.status_code != 200:
            print(f"Token exchange failed: {token_response.text}")
            return None
        
        token_json = token_response.json()
        access_token = token_json.get("access_token")
        
        if not access_token:
            print("No access token received")
            return None
        
        # Get user info using access token
        userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
        userinfo_response = http_requests.get(
            userinfo_url,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        
        if userinfo_response.status_code != 200:
            print(f"User info fetch failed: {userinfo_response.text}")
            return None
        
        user_data = userinfo_response.json()
        
        return {
            "google_id": user_data.get('id'),
            "email": user_data.get('email', ''),
            "name": user_data.get('name', ''),
            "picture": user_data.get('picture', '')
        }
    except Exception as e:
        print(f"Google code exchange error: {e}")
        return None

# def get_github_auth_url() -> str:
#     """Generate GitHub OAuth authorization URL"""
#     try:
#         if not GITHUB_CLIENT_ID:
#             return ""
        
#         scopes = "%20".join(GITHUB_SCOPES)
#         auth_url = f"https://github.com/login/oauth/authorize?client_id={GITHUB_CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope={scopes}"
#         return auth_url
#     except Exception as e:
#         print(f"Error generating GitHub auth URL: {e}")
#         return ""

def get_github_auth_url() -> str:
    if not GITHUB_CLIENT_ID or not REDIRECT_URI:
        return ""

    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(GITHUB_SCOPES),
        "state": "github"  # this helps distinguish providers
    }
    return f"https://github.com/login/oauth/authorize?{urlencode(params)}"

def exchange_github_code(code: str) -> Optional[Dict]:
    """Exchange GitHub authorization code for access token and get user info"""
    try:
        import requests as http_requests
        
        # Exchange code for access token
        token_url = "https://github.com/login/oauth/access_token"
        token_data = {
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": REDIRECT_URI
        }
        
        token_response = http_requests.post(
            token_url,
            data=token_data,
            headers={"Accept": "application/json"}
        )
        
        if token_response.status_code != 200:
            print(f"Token exchange failed: {token_response.text}")
            return None
        
        token_json = token_response.json()
        access_token = token_json.get("access_token")
        
        if not access_token:
            print("No access token received")
            return None
        
        # Get user information
        user_url = "https://api.github.com/user"
        user_response = http_requests.get(
            user_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json"
            }
        )
        
        if user_response.status_code != 200:
            print(f"User info fetch failed: {user_response.text}")
            return None
        
        user_data = user_response.json()
        
        # Get user email if not public
        email = user_data.get("email")
        if not email:
            email_url = "https://api.github.com/user/emails"
            email_response = http_requests.get(
                email_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json"
                }
            )
            if email_response.status_code == 200:
                emails = email_response.json()
                # Get primary email
                for e in emails:
                    if e.get("primary"):
                        email = e.get("email")
                        break
                if not email and emails:
                    email = emails[0].get("email")
        
        return {
            "github_id": str(user_data.get("id")),
            "email": email or f"{user_data.get('id')}@github.users.noreply.com",
            "name": user_data.get("name") or user_data.get("login"),
            "username": user_data.get("login"),
            "picture": user_data.get("avatar_url")
        }
    except Exception as e:
        print(f"GitHub code exchange error: {e}")
        return None

def create_session(user_id: int) -> int:
    """Create a new session for user"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO user_sessions (user_id)
            VALUES (?)
        """, (user_id,))
        
        session_id = cursor.lastrowid
        
        conn.commit()
        conn.close()
        return session_id
    except Exception as e:
        print(f"Error creating session: {e}")
        return 0

def end_session(session_id: int, docs_processed: int):
    """End user session"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE user_sessions
            SET session_end = ?, documents_processed = ?
            WHERE session_id = ?
        """, (datetime.now(), docs_processed, session_id))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error ending session: {e}")

def add_audit_entry(user_id: int, session_id: int, action: str, file_name: str, 
                    doc_type: str, status: str, details: str = ""):
    """Add entry to audit trail"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO audit_trail (user_id, session_id, action, file_name, doc_type, status, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, session_id, action, file_name, doc_type, status, details))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error adding audit entry: {e}")

def get_user_audit_trail(user_id: int, limit: int = 100) -> List[Dict]:
    """Get audit trail for specific user"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT timestamp, action, file_name, doc_type, status, details
            FROM audit_trail
            WHERE user_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (user_id, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {
                "timestamp": row[0],
                "action": row[1],
                "file": row[2],
                "type": row[3],
                "status": row[4],
                "details": row[5]
            }
            for row in rows
        ]
    except Exception as e:
        print(f"Error getting audit trail: {e}")
        return []

def save_processed_document(user_id: int, session_id: int, file_name: str, 
                           doc_type: str, extracted_data: str, metadata: str, status: str):
    """Save processed document to database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO processed_documents 
            (user_id, session_id, file_name, doc_type, extracted_data, metadata, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, session_id, file_name, doc_type, extracted_data, metadata, status))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error saving document: {e}")

def get_user_documents(user_id: int, limit: int = 50) -> List[Dict]:
    """Get user's processed documents"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT file_name, doc_type, processed_at, status, extracted_data
            FROM processed_documents
            WHERE user_id = ?
            ORDER BY processed_at DESC
            LIMIT ?
        """, (user_id, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {
                "file_name": row[0],
                "doc_type": row[1],
                "processed_at": row[2],
                "status": row[3],
                "data": row[4]
            }
            for row in rows
        ]
    except Exception as e:
        print(f"Error getting documents: {e}")
        return []

def update_user_stats(user_id: int, processed: int = 0, matched: int = 0, flagged: int = 0,
                     invoices: int = 0, pos: int = 0, statements: int = 0):
    """Update user statistics"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE user_stats
            SET total_processed = total_processed + ?,
                total_matched = total_matched + ?,
                total_flagged = total_flagged + ?,
                total_invoices = total_invoices + ?,
                total_pos = total_pos + ?,
                total_statements = total_statements + ?,
                last_updated = ?
            WHERE user_id = ?
        """, (processed, matched, flagged, invoices, pos, statements, datetime.now(), user_id))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error updating stats: {e}")

def get_user_stats(user_id: int) -> Dict:
    """Get user statistics"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT total_processed, total_matched, total_flagged, 
                   total_invoices, total_pos, total_statements
            FROM user_stats
            WHERE user_id = ?
        """, (user_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return {
                "processed": row[0],
                "matched": row[1],
                "flagged": row[2],
                "invoices": row[3],
                "pos": row[4],
                "statements": row[5]
            }
        return {"processed": 0, "matched": 0, "flagged": 0, "invoices": 0, "pos": 0, "statements": 0}
    except Exception as e:
        print(f"Error getting stats: {e}")
        return {"processed": 0, "matched": 0, "flagged": 0, "invoices": 0, "pos": 0, "statements": 0}

def save_reconciliation(user_id: int, session_id: int, invoice_file: str, po_file: str,
                       risk_level: str, matched: bool, variance_amount: float,
                       variance_pct: float, discrepancies: str):
    """Save reconciliation result"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO reconciliation_history 
            (user_id, session_id, invoice_file, po_file, risk_level, matched, 
             variance_amount, variance_percentage, discrepancies)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, session_id, invoice_file, po_file, risk_level, matched,
              variance_amount, variance_pct, discrepancies))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error saving reconciliation: {e}")

def get_user_reconciliations(user_id: int, limit: int = 50) -> List[Dict]:
    """Get user's reconciliation history"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT invoice_file, po_file, reconciled_at, risk_level, matched,
                   variance_amount, variance_percentage, discrepancies
            FROM reconciliation_history
            WHERE user_id = ?
            ORDER BY reconciled_at DESC
            LIMIT ?
        """, (user_id, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {
                "invoice": row[0],
                "po": row[1],
                "date": row[2],
                "risk": row[3],
                "matched": row[4],
                "variance_amount": row[5],
                "variance_pct": row[6],
                "discrepancies": row[7]
            }
            for row in rows
        ]
    except Exception as e:
        print(f"Error getting reconciliations: {e}")
        return []

def get_total_users() -> int:
    """Get total number of users"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except:
        return 0

# Initialize database on module import
init_database()
