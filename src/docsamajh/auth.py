"""
Authentication and User Management Module
Handles user registration, login, session management, and data isolation
"""

import hashlib
import sqlite3
import os
from datetime import datetime
from typing import Optional, Dict, List
import streamlit as st

# Database setup
DB_PATH = "docsamajh_users.db"

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
            password_hash TEXT NOT NULL,
            full_name TEXT,
            company TEXT,
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

def create_user(username: str, email: str, password: str, full_name: str = "", company: str = "") -> bool:
    """Create a new user account"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        password_hash = hash_password(password)
        
        cursor.execute("""
            INSERT INTO users (username, email, password_hash, full_name, company)
            VALUES (?, ?, ?, ?, ?)
        """, (username, email, password_hash, full_name, company))
        
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
            SELECT user_id, username, email, full_name, company, created_at, is_active
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
                "is_active": user[6]
            }
            
            conn.close()
            return user_data
        
        conn.close()
        return None
    except Exception as e:
        print(f"Authentication error: {e}")
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
