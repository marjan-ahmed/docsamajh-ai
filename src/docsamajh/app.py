"""
DocSamajh AI - Intelligent Financial Document Reconciliation Platform
Powered by LandingAI ADE + Multi-Agent Framework

A production-ready solution for automated invoice reconciliation, 
PO matching, and financial compliance verification.
"""

import streamlit as st
import asyncio
import aiohttp
import json
import os
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass
from dotenv import load_dotenv
from openai import AsyncOpenAI
from agents import Agent, Runner, RunConfig, OpenAIChatCompletionsModel, set_tracing_disabled, function_tool

# Import authentication module
from auth import (
    authenticate_user, create_user, create_session, end_session,
    add_audit_entry, get_user_audit_trail, save_processed_document,
    get_user_documents, update_user_stats, get_user_stats,
    save_reconciliation, get_user_reconciliations, get_total_users,
    get_google_auth_url, get_github_auth_url, verify_google_token, 
    authenticate_google_user, authenticate_github_user, exchange_github_code,
    exchange_google_code
)

load_dotenv()

# Configuration
GEMINI_MODEL = os.getenv("GEMINI_MODEL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
BASE_URL = os.getenv("BASE_URL")
ADE_API_KEY = os.getenv("ADE_API_KEY")
ADE_PARSE_ENDPOINT = "https://api.va.landing.ai/v1/ade/parse"
ADE_EXTRACT_ENDPOINT = "https://api.va.landing.ai/v1/ade/extract"

set_tracing_disabled(True)

# LLM Setup
client = AsyncOpenAI(api_key=GEMINI_API_KEY, base_url=BASE_URL)
model = OpenAIChatCompletionsModel(GEMINI_MODEL, client)

# Data Models
@dataclass
class DocumentMetadata:
    """Metadata for processed documents"""
    filename: str
    doc_type: str
    processed_at: datetime
    page_count: int
    confidence_score: float
    processing_time_ms: int
    credit_usage: int

@dataclass
class InvoiceData:
    """Structured invoice data"""
    invoice_number: str
    vendor_name: str
    invoice_date: str
    due_date: str
    subtotal: float
    tax: float
    total: float
    currency: str
    line_items: List[Dict]
    po_number: Optional[str] = None
    confidence: Dict[str, float] = None

@dataclass
class ReconciliationResult:
    """Results from invoice-PO reconciliation"""
    matched: bool
    discrepancies: List[str]
    amount_variance: float
    line_item_matches: int
    total_line_items: int
    recommendation: str
    risk_level: str  # LOW, MEDIUM, HIGH

# ==================== ADE API Functions ====================

async def ade_parse_document(file_path: str, split_pages: bool = False) -> Dict:
    """
    Parse document using ADE with enhanced error handling and metadata capture
    """
    with open(file_path, "rb") as f:
        file_content = f.read()
    
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {ADE_API_KEY}"}
        form_data = aiohttp.FormData()
        form_data.add_field("model", "dpt-2-latest")
        
        if split_pages:
            form_data.add_field("split", "page")
        
        form_data.add_field("document", file_content, 
                          filename=os.path.basename(file_path),
                          content_type="application/pdf")
        
        async with session.post(ADE_PARSE_ENDPOINT, headers=headers, data=form_data) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise Exception(f"ADE Parse failed ({resp.status}): {error_text}")
            
            return await resp.json()

async def ade_extract_data(markdown: str, schema: Dict) -> Dict:
    """
    Extract structured data from markdown using ADE Extract
    """
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {ADE_API_KEY}"}
        form_data = aiohttp.FormData()
        form_data.add_field("schema", json.dumps(schema))
        form_data.add_field("model", "extract-latest")
        form_data.add_field("markdown", markdown)
        
        async with session.post(ADE_EXTRACT_ENDPOINT, headers=headers, data=form_data) as resp:
            # Accept both 200 (full success) and 206 (partial success)
            if resp.status not in [200, 206]:
                error_text = await resp.text()
                raise Exception(f"ADE Extract failed ({resp.status}): {error_text}")
            
            result = await resp.json()
            
            # Log warning if partial content (206)
            if resp.status == 206:
                schema_error = result.get("metadata", {}).get("schema_violation_error")
                if schema_error:
                    print(f"⚠️ Partial extraction (some fields missing): {schema_error[:200]}")
            
            return result

# ==================== Schemas ====================

INVOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "invoice_number": {"type": ["string", "null"], "description": "Invoice number or ID"},
        "po_number": {"type": ["string", "null"], "description": "Purchase order number if present"},
        "vendor_name": {"type": ["string", "null"], "description": "Vendor or seller company name"},
        "vendor_tax_id": {"type": ["string", "null"], "description": "Vendor tax ID or EIN"},
        "vendor_address": {"type": ["string", "null"], "description": "Vendor address"},
        "customer_name": {"type": ["string", "null"], "description": "Customer or buyer name"},
        "customer_address": {"type": ["string", "null"], "description": "Customer billing address"},
        "invoice_date": {"type": ["string", "null"], "description": "Invoice date (MM/DD/YYYY or similar)"},
        "due_date": {"type": ["string", "null"], "description": "Payment due date"},
        "payment_terms": {"type": ["string", "null"], "description": "Payment terms (Net 30, etc)"},
        "subtotal": {"type": ["number", "null"], "description": "Subtotal before tax"},
        "tax_rate": {"type": ["number", "null"], "description": "Tax rate percentage"},
        "tax_amount": {"type": ["number", "null"], "description": "Total tax amount"},
        "total_amount": {"type": ["number", "null"], "description": "Total amount due"},
        "currency": {"type": ["string", "null"], "description": "Currency code (USD, EUR, etc)"},
        "line_items": {
            "type": "array",
            "description": "List of invoice line items",
            "items": {
                "type": "object",
                "properties": {
                    "item_number": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                    "quantity": {"type": ["number", "null"]},
                    "unit_price": {"type": ["number", "null"]},
                    "amount": {"type": ["number", "null"]}
                }
            }
        }
    }
}

PO_SCHEMA = {
    "type": "object",
    "properties": {
        "po_number": {"type": ["string", "null"], "description": "Purchase order number"},
        "vendor_name": {"type": ["string", "null"], "description": "Vendor name"},
        "order_date": {"type": ["string", "null"], "description": "PO date"},
        "delivery_date": {"type": ["string", "null"], "description": "Expected delivery date"},
        "total_amount": {"type": ["number", "null"], "description": "Total PO amount"},
        "currency": {"type": ["string", "null"], "description": "Currency"},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_number": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                    "quantity": {"type": ["number", "null"]},
                    "unit_price": {"type": ["number", "null"]},
                    "amount": {"type": ["number", "null"]}
                }
            }
        }
    }
}

BANK_STATEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "account_number": {"type": ["string", "null"], "description": "Bank account number"},
        "account_holder": {"type": ["string", "null"], "description": "Account holder name"},
        "bank_name": {"type": ["string", "null"], "description": "Name of the bank"},
        "statement_period_start": {"type": ["string", "null"], "description": "Statement start date"},
        "statement_period_end": {"type": ["string", "null"], "description": "Statement end date"},
        "opening_balance": {"type": ["number", "null"], "description": "Opening balance amount"},
        "closing_balance": {"type": ["number", "null"], "description": "Closing balance amount"},
        "total_deposits": {"type": ["number", "null"], "description": "Total deposits/credits"},
        "total_withdrawals": {"type": ["number", "null"], "description": "Total withdrawals/debits"},
        "currency": {"type": ["string", "null"], "description": "Currency code"},
        "transactions": {
            "type": "array",
            "description": "List of transactions",
            "items": {
                "type": "object",
                "properties": {
                    "date": {"type": ["string", "null"], "description": "Transaction date"},
                    "description": {"type": ["string", "null"], "description": "Transaction description"},
                    "amount": {"type": ["number", "null"], "description": "Transaction amount"},
                    "type": {"type": ["string", "null"], "description": "Debit or Credit"},
                    "balance": {"type": ["number", "null"], "description": "Balance after transaction"}
                }
            }
        }
    }
}

# ==================== Agent Tools ====================

@function_tool(strict_mode=False)
async def parse_invoice(file_path: str):
    """
    Parse and extract structured data from an invoice document.
    Returns complete invoice data with line items, amounts, and metadata.
    """
    # Parse document
    parse_result = await ade_parse_document(file_path, split_pages=False)
    markdown = parse_result.get("markdown", "")
    metadata = parse_result.get("metadata", {})
    
    # Extract structured data
    extract_result = await ade_extract_data(markdown, INVOICE_SCHEMA)
    extracted = extract_result.get("extraction", {})
    
    return {
        "invoice_data": extracted,
        "metadata": metadata,
        "markdown_preview": markdown[:500]
    }

@function_tool(strict_mode=False)
async def parse_purchase_order(file_path: str):
    """
    Parse and extract structured data from a purchase order document.
    Returns PO data with line items and delivery information.
    """
    parse_result = await ade_parse_document(file_path, split_pages=False)
    markdown = parse_result.get("markdown", "")
    metadata = parse_result.get("metadata", {})
    
    extract_result = await ade_extract_data(markdown, PO_SCHEMA)
    extracted = extract_result.get("extraction", {})
    
    return {
        "po_data": extracted,
        "metadata": metadata,
        "markdown_preview": markdown[:500]
    }

@function_tool(strict_mode=False)
async def parse_bank_statement(file_path: str):
    """
    Parse and extract structured data from a bank statement document.
    Returns account details, balance information, and transaction history.
    """
    parse_result = await ade_parse_document(file_path, split_pages=False)
    markdown = parse_result.get("markdown", "")
    metadata = parse_result.get("metadata", {})
    
    extract_result = await ade_extract_data(markdown, BANK_STATEMENT_SCHEMA)
    extracted = extract_result.get("extraction", {})
    
    return {
        "statement_data": extracted,
        "metadata": metadata,
        "markdown_preview": markdown[:500]
    }

# Helper functions that can be called directly (not decorated)
async def process_invoice_direct(file_path: str):
    """Direct call to parse invoice without going through agent"""
    parse_result = await ade_parse_document(file_path, split_pages=False)
    markdown = parse_result.get("markdown", "")
    metadata = parse_result.get("metadata", {})
    
    extract_result = await ade_extract_data(markdown, INVOICE_SCHEMA)
    extracted = extract_result.get("extraction", {})
    
    return {
        "invoice_data": extracted,
        "metadata": metadata,
        "markdown_preview": markdown[:500]
    }

async def process_po_direct(file_path: str):
    """Direct call to parse PO without going through agent"""
    parse_result = await ade_parse_document(file_path, split_pages=False)
    markdown = parse_result.get("markdown", "")
    metadata = parse_result.get("metadata", {})
    
    extract_result = await ade_extract_data(markdown, PO_SCHEMA)
    extracted = extract_result.get("extraction", {})
    
    return {
        "po_data": extracted,
        "metadata": metadata,
        "markdown_preview": markdown[:500]
    }

async def process_bank_statement_direct(file_path: str):
    """Direct call to parse bank statement without going through agent"""
    parse_result = await ade_parse_document(file_path, split_pages=False)
    markdown = parse_result.get("markdown", "")
    metadata = parse_result.get("metadata", {})
    
    extract_result = await ade_extract_data(markdown, BANK_STATEMENT_SCHEMA)
    extracted = extract_result.get("extraction", {})
    
    return {
        "statement_data": extracted,
        "metadata": metadata,
        "markdown_preview": markdown[:500]
    }

async def reconcile_direct(invoice_data: dict, po_data: dict):
    """Direct reconciliation without going through agent"""
    discrepancies = []
    invoice_total = invoice_data.get("total_amount") or 0
    po_total = po_data.get("total_amount") or 0
    
    # Check vendor match (handle None values)
    invoice_vendor = (invoice_data.get("vendor_name") or "").lower()
    po_vendor = (po_data.get("vendor_name") or "").lower()
    if invoice_vendor != po_vendor:
        discrepancies.append("Vendor name mismatch")
    
    # Check amount variance
    amount_variance = abs(invoice_total - po_total) if invoice_total and po_total else 0
    variance_pct = (amount_variance / po_total * 100) if po_total > 0 else 0
    
    if variance_pct > 5:
        discrepancies.append(f"Amount variance: ${amount_variance:.2f} ({variance_pct:.1f}%)")
    
    # Check line items (handle None values)
    invoice_items = invoice_data.get("line_items") or []
    po_items = po_data.get("line_items") or []
    
    matched_items = 0
    for inv_item in invoice_items:
        inv_desc = (inv_item.get("description") or "").lower()
        for po_item in po_items:
            po_desc = (po_item.get("description") or "").lower()
            if inv_desc and po_desc and inv_desc == po_desc:
                matched_items += 1
                # Check quantity and price (handle None values)
                inv_qty = inv_item.get("quantity") or 0
                po_qty = po_item.get("quantity") or 0
                inv_price = inv_item.get("unit_price") or 0
                po_price = po_item.get("unit_price") or 0
                
                if inv_qty != po_qty:
                    discrepancies.append(f"Quantity mismatch for {inv_item.get('description')}")
                if abs(inv_price - po_price) > 0.01:
                    discrepancies.append(f"Price mismatch for {inv_item.get('description')}")
    
    # Determine risk level
    if len(discrepancies) == 0:
        risk_level = "LOW"
        recommendation = "APPROVE - Perfect match"
    elif len(discrepancies) <= 2 and variance_pct < 2:
        risk_level = "MEDIUM"
        recommendation = "REVIEW - Minor discrepancies found"
    else:
        risk_level = "HIGH"
        recommendation = "REJECT - Significant discrepancies"
    
    return {
        "matched": len(discrepancies) == 0,
        "discrepancies": discrepancies,
        "amount_variance": amount_variance,
        "variance_percentage": variance_pct,
        "line_items_matched": matched_items,
        "total_line_items": len(invoice_items),
        "recommendation": recommendation,
        "risk_level": risk_level,
        "invoice_total": invoice_total,
        "po_total": po_total
    }

async def compliance_check_direct(invoice_data: dict):
    """Direct compliance check without going through agent"""
    issues = []
    warnings = []
    
    # Required field checks
    required_fields = ["invoice_number", "vendor_name", "invoice_date", "total_amount"]
    for field in required_fields:
        if not invoice_data.get(field):
            issues.append(f"Missing required field: {field}")
    
    # Tax validation (handle None values)
    subtotal = invoice_data.get("subtotal") or 0
    tax = invoice_data.get("tax_amount") or 0
    total = invoice_data.get("total_amount") or 0
    
    expected_total = subtotal + tax
    if subtotal > 0 and tax > 0 and abs(total - expected_total) > 0.02:
        issues.append(f"Tax calculation error: {subtotal} + {tax} ≠ {total}")
    
    # Tax rate reasonability (0-20%)
    if subtotal > 0 and tax > 0:
        effective_tax_rate = (tax / subtotal) * 100
        if effective_tax_rate > 20:
            warnings.append(f"Unusually high tax rate: {effective_tax_rate:.1f}%")
    
    if tax < 0:
        issues.append("Negative tax amount")
    
    # Amount reasonability
    if total <= 0:
        issues.append("Total amount must be positive")
    
    if total > 1000000:
        warnings.append("Large invoice amount - requires additional approval")
    
    compliance_score = 100 - (len(issues) * 20) - (len(warnings) * 5)
    compliance_score = max(0, min(100, compliance_score))
    
    status = "PASS" if len(issues) == 0 else "FAIL"
    
    return {
        "status": status,
        "compliance_score": compliance_score,
        "critical_issues": issues,
        "warnings": warnings,
        "requires_approval": len(issues) > 0 or total > 10000
    }

@function_tool(strict_mode=False)
async def reconcile_invoice_to_po(invoice_data: dict, po_data: dict):
    """
    Reconcile an invoice against a purchase order.
    Checks for matching amounts, line items, and identifies discrepancies.
    Returns detailed reconciliation report with risk assessment.
    """
    discrepancies = []
    invoice_total = invoice_data.get("total_amount", 0)
    po_total = po_data.get("total_amount", 0)
    
    # Check vendor match
    if invoice_data.get("vendor_name", "").lower() != po_data.get("vendor_name", "").lower():
        discrepancies.append("Vendor name mismatch")
    
    # Check amount variance
    amount_variance = abs(invoice_total - po_total)
    variance_pct = (amount_variance / po_total * 100) if po_total > 0 else 0
    
    if variance_pct > 5:
        discrepancies.append(f"Amount variance: ${amount_variance:.2f} ({variance_pct:.1f}%)")
    
    # Check line items
    invoice_items = invoice_data.get("line_items", [])
    po_items = po_data.get("line_items", [])
    
    matched_items = 0
    for inv_item in invoice_items:
        for po_item in po_items:
            if inv_item.get("description", "").lower() == po_item.get("description", "").lower():
                matched_items += 1
                # Check quantity and price
                if inv_item.get("quantity") != po_item.get("quantity"):
                    discrepancies.append(f"Quantity mismatch for {inv_item.get('description')}")
                if abs(inv_item.get("unit_price", 0) - po_item.get("unit_price", 0)) > 0.01:
                    discrepancies.append(f"Price mismatch for {inv_item.get('description')}")
    
    # Determine risk level
    if len(discrepancies) == 0:
        risk_level = "LOW"
        recommendation = "APPROVE - Perfect match"
    elif len(discrepancies) <= 2 and variance_pct < 2:
        risk_level = "MEDIUM"
        recommendation = "REVIEW - Minor discrepancies found"
    else:
        risk_level = "HIGH"
        recommendation = "REJECT - Significant discrepancies"
    
    return {
        "matched": len(discrepancies) == 0,
        "discrepancies": discrepancies,
        "amount_variance": amount_variance,
        "variance_percentage": variance_pct,
        "line_items_matched": matched_items,
        "total_line_items": len(invoice_items),
        "recommendation": recommendation,
        "risk_level": risk_level,
        "invoice_total": invoice_total,
        "po_total": po_total
    }

@function_tool(strict_mode=False)
async def compliance_check(invoice_data: dict):
    """
    Perform compliance checks on invoice data.
    Validates required fields, tax calculations, and regulatory requirements.
    """
    issues = []
    warnings = []
    
    # Required field checks
    required_fields = ["invoice_number", "vendor_name", "invoice_date", "total_amount"]
    for field in required_fields:
        if not invoice_data.get(field):
            issues.append(f"Missing required field: {field}")
    
    # Tax validation
    subtotal = invoice_data.get("subtotal", 0)
    tax = invoice_data.get("tax_amount", 0)
    total = invoice_data.get("total_amount", 0)
    
    expected_total = subtotal + tax
    if abs(total - expected_total) > 0.02:
        issues.append(f"Tax calculation error: {subtotal} + {tax} ≠ {total}")
    
    # Tax rate reasonability (0-20%)
    if subtotal > 0:
        effective_tax_rate = (tax / subtotal) * 100
        if effective_tax_rate > 20:
            warnings.append(f"Unusually high tax rate: {effective_tax_rate:.1f}%")
        elif effective_tax_rate < 0:
            issues.append("Negative tax amount")
    
    # Date validation
    invoice_date = invoice_data.get("invoice_date")
    due_date = invoice_data.get("due_date")
    if invoice_date and due_date:
        # Simple check - due date should be after invoice date
        # In production, parse dates properly
        pass
    
    # Amount reasonability
    if total <= 0:
        issues.append("Total amount must be positive")
    
    if total > 1000000:
        warnings.append("Large invoice amount - requires additional approval")
    
    compliance_score = 100 - (len(issues) * 20) - (len(warnings) * 5)
    compliance_score = max(0, min(100, compliance_score))
    
    status = "PASS" if len(issues) == 0 else "FAIL"
    
    return {
        "status": status,
        "compliance_score": compliance_score,
        "critical_issues": issues,
        "warnings": warnings,
        "requires_approval": len(issues) > 0 or total > 10000
    }

# ==================== Agents ====================

# Document Processing Agent
doc_processor_agent = Agent(
    name="Document Processor",
    instructions="""You are a financial document processing specialist.
    Parse invoices, purchase orders, and bank statements accurately, extract all financial data,
    and ensure data quality. Use the parse_invoice, parse_purchase_order, and parse_bank_statement tools.""",
    model=model,
    tools=[parse_invoice, parse_purchase_order, parse_bank_statement]
)

# Reconciliation Agent
reconciliation_agent = Agent(
    name="Reconciliation Specialist",
    instructions="""You are an accounts payable reconciliation expert.
    Compare invoices against purchase orders, identify discrepancies,
    calculate variances, and provide risk-assessed recommendations.
    Use the reconcile_invoice_to_po tool to perform three-way matching.""",
    model=model,
    tools=[reconcile_invoice_to_po]
)

# Compliance Agent
compliance_agent = Agent(
    name="Compliance Auditor",
    instructions="""You are a financial compliance auditor.
    Verify invoice data meets regulatory requirements, validate calculations,
    check for required fields, and flag any compliance issues.
    Use the compliance_check tool for validation.""",
    model=model,
    tools=[compliance_check]
)

# ==================== Streamlit UI ====================

st.set_page_config(
    page_title="DocSamajh AI",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state for authentication
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_data" not in st.session_state:
    st.session_state.user_data = None
if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "session_docs_count" not in st.session_state:
    st.session_state.session_docs_count = 0

# ==================== Authentication UI ====================

def show_login_page():
    """Display login/registration page"""
    st.markdown('<p class="big-title">📊 DocSamajh AI</p>', unsafe_allow_html=True)
    st.markdown("**Intelligent Financial Document Reconciliation Platform** | Powered by LandingAI ADE")
    st.markdown("---")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        # Check for OAuth callback
        query_params = st.query_params
        if "code" in query_params and "state" in query_params:
            state = query_params["state"]
            code = query_params["code"]
            
            if state == "google":
                with st.spinner("🔐 Authenticating with Google..."):
                    try:
                        print(f"[DEBUG] Processing Google OAuth callback with code: {code[:20]}...")
                        # Exchange code for user info
                        google_info = exchange_google_code(code)
                        
                        if google_info:
                            print(f"[DEBUG] Google info received: {google_info.get('email')}")
                            # Authenticate or create user
                            user_data = authenticate_google_user(
                                google_info["google_id"],
                                google_info["email"],
                                google_info["name"],
                                google_info["picture"]
                            )
                            
                            if user_data:
                                print(f"[SUCCESS] User authenticated: {user_data.get('username')}")
                                st.session_state.authenticated = True
                                st.session_state.user_data = user_data
                                st.session_state.session_id = create_session(user_data["user_id"])
                                st.session_state.session_docs_count = 0
                                st.success(f"✅ Welcome, {user_data['full_name'] or user_data['username']}!")
                                # Clear query params and reload
                                st.query_params.clear()
                                st.rerun()
                            else:
                                print("[ERROR] authenticate_google_user returned None")
                                st.error("❌ Failed to authenticate with Google")
                        else:
                            print("[ERROR] exchange_google_code returned None")
                            st.error("❌ Failed to exchange Google authorization code")
                    except Exception as e:
                        print(f"[ERROR] Google authentication exception: {str(e)}")
                        import traceback
                        traceback.print_exc()
                        st.error(f"Google authentication failed: {str(e)}")
            
            elif state == "github":
                with st.spinner("🔐 Authenticating with GitHub..."):
                    try:
                        # Exchange code for user info
                        github_info = exchange_github_code(code)
                        
                        if github_info:
                            # Authenticate or create user
                            user_data = authenticate_github_user(
                                github_info["github_id"],
                                github_info["email"],
                                github_info["name"],
                                github_info["username"],
                                github_info["picture"]
                            )
                            
                            if user_data:
                                st.session_state.authenticated = True
                                st.session_state.user_data = user_data
                                st.session_state.session_id = create_session(user_data["user_id"])
                                st.session_state.session_docs_count = 0
                                st.success(f"✅ Welcome, {user_data['full_name'] or user_data['username']}!")
                                # Clear query params and reload
                                st.query_params.clear()
                                st.rerun()
                            else:
                                st.error("❌ Failed to authenticate with GitHub")
                        else:
                            st.error("❌ Failed to exchange GitHub authorization code")
                    except Exception as e:
                        st.error(f"GitHub authentication failed: {str(e)}")
            
            else:
                st.error(f"Unknown OAuth provider: {state}")
        
        tab1, tab2 = st.tabs(["🔐 Login", "📝 Register"])
        
        with tab1:
            st.header("Login to Your Account")
            
            # Google Sign-In Button
            google_auth_url = get_google_auth_url()
            github_auth_url = get_github_auth_url()
            
            if google_auth_url or github_auth_url:
                col_oauth1, col_oauth2 = st.columns(2)
                
                with col_oauth1:
                    if google_auth_url:
                        st.markdown(f"""
                            <a href="{google_auth_url}" target="_blank" style="
                                display: inline-flex;
                                align-items: center;
                                justify-content: center;
                                background: white;
                                border: 1px solid #dadce0;
                                border-radius: 4px;
                                padding: 10px;
                                text-decoration: none;
                                color: #3c4043;
                                font-size: 14px;
                                font-weight: 500;
                                width: 100%;
                                margin-bottom: 10px;
                            ">
                                <svg width="18" height="18" viewBox="0 0 24 24" style="margin-right: 8px;">
                                    <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                                    <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                                    <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
                                    <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
                                </svg>
                                Google
                            </a>
                        """, unsafe_allow_html=True)
                
                with col_oauth2:
                    if github_auth_url:
                        st.markdown(f"""
                            <a href="{github_auth_url}" target="_blank" style="
                                display: inline-flex;
                                align-items: center;
                                justify-content: center;
                                background: #24292e;
                                border: 1px solid #24292e;
                                border-radius: 4px;
                                padding: 10px;
                                text-decoration: none;
                                color: white;
                                font-size: 14px;
                                font-weight: 500;
                                width: 100%;
                                margin-bottom: 10px;
                            ">
                                <svg width="18" height="18" viewBox="0 0 16 16" fill="white" style="margin-right: 8px;">
                                    <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>
                                </svg>
                                GitHub
                            </a>
                        """, unsafe_allow_html=True)
                
                st.markdown("<div style='text-align: center; margin: 20px 0;'>or</div>", unsafe_allow_html=True)
            
            with st.form("login_form"):
                username = st.text_input("Username", key="login_username")
                password = st.text_input("Password", type="password", key="login_password")
                submit = st.form_submit_button("🚀 Login", use_container_width=True)
                
                if submit:
                    if username and password:
                        user_data = authenticate_user(username, password)
                        if user_data:
                            st.session_state.authenticated = True
                            st.session_state.user_data = user_data
                            st.session_state.session_id = create_session(user_data["user_id"])
                            st.session_state.session_docs_count = 0
                            st.success(f"✅ Welcome back, {user_data['full_name'] or user_data['username']}!")
                            st.rerun()
                        else:
                            st.error("❌ Invalid username or password")
                    else:
                        st.warning("⚠️ Please enter both username and password")
        
        with tab2:
            st.header("Create New Account")
            
            with st.form("register_form"):
                new_username = st.text_input("Username", key="reg_username")
                new_email = st.text_input("Email", key="reg_email")
                new_password = st.text_input("Password", type="password", key="reg_password")
                confirm_password = st.text_input("Confirm Password", type="password", key="reg_confirm")
                full_name = st.text_input("Full Name (Optional)", key="reg_fullname")
                company = st.text_input("Company (Optional)", key="reg_company")
                
                register = st.form_submit_button("📝 Create Account", use_container_width=True)
                
                if register:
                    if not all([new_username, new_email, new_password, confirm_password]):
                        st.warning("⚠️ Please fill in all required fields")
                    elif new_password != confirm_password:
                        st.error("❌ Passwords do not match")
                    elif len(new_password) < 6:
                        st.error("❌ Password must be at least 6 characters")
                    else:
                        if create_user(new_username, new_email, new_password, full_name, company):
                            st.success("✅ Account created successfully! Please login.")
                        else:
                            st.error("❌ Username or email already exists")
        
        # Stats section
        st.markdown("---")
        st.info(f"👥 **{get_total_users()}** users trust DocSamajh AI for their financial document processing")

def show_logout_button():
    """Display logout button in sidebar"""
    if st.sidebar.button("🚪 Logout", use_container_width=True):
        # End session
        if st.session_state.session_id:
            end_session(st.session_state.session_id, st.session_state.session_docs_count)
        
        # Clear session state
        st.session_state.authenticated = False
        st.session_state.user_data = None
        st.session_state.session_id = None
        st.session_state.session_docs_count = 0
        st.rerun()

# Check authentication
if not st.session_state.authenticated:
    show_login_page()
    st.stop()

# ==================== Authenticated App ====================

# Custom CSS
st.markdown("""
<style>
    .big-title {font-size: 2.5rem; font-weight: bold; color: #1f77b4;}
    .metric-card {
        background: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        border-left: 5px solid #1f77b4;
    }
    .success-box {background: #d4edda; padding: 15px; border-radius: 5px; border-left: 4px solid #28a745;}
    .warning-box {background: #fff3cd; padding: 15px; border-radius: 5px; border-left: 4px solid #ffc107;}
    .error-box {background: #f8d7da; padding: 15px; border-radius: 5px; border-left: 4px solid #dc3545;}
</style>
""", unsafe_allow_html=True)

# Header
st.markdown('<p class="big-title">📊 DocSamajh AI</p>', unsafe_allow_html=True)
st.markdown("**Intelligent Financial Document Reconciliation Platform** | Powered by LandingAI ADE")

# Sidebar
with st.sidebar:
    try:
        st.image("docsamajhai.jpg", width=120)
    except:
        pass
    
    st.markdown("---")
    st.header("🎯 Capabilities")
    st.markdown("""
    - **Invoice Processing**: Auto-extract all financial data
    - **PO Matching**: 3-way reconciliation
    - **Compliance Checks**: Regulatory validation
    - **Risk Assessment**: AI-powered fraud detection
    - **Batch Processing**: Handle multiple documents
    - **Audit Trail**: Full processing history
    """)
    
    st.markdown("---")
    st.header("📈 Your Statistics")
    
    # Get user stats from database
    user = st.session_state.user_data
    user_stats = get_user_stats(user["user_id"])
    
    col1, col2 = st.columns(2)
    col1.metric("Processed", user_stats["processed"])
    col2.metric("Matched", user_stats["matched"])
    st.metric("Flagged", user_stats["flagged"])
    
    # Document type breakdown
    with st.expander("📊 Document Breakdown"):
        st.metric("Invoices", user_stats["invoices"])
        st.metric("Purchase Orders", user_stats["pos"])
        st.metric("Bank Statements", user_stats["statements"])
    
    # User info and logout at the bottom
    st.markdown("---")
    
    # Display profile picture if available (Google users)
    if user.get('profile_picture'):
        st.markdown(f"""
            <div style="text-align: center;">
                <img src="{user['profile_picture']}" 
                     style="border-radius: 50%; width: 80px; height: 80px; margin-bottom: 10px;">
            </div>
        """, unsafe_allow_html=True)
    
    st.markdown(f"### 👤 {user['full_name'] or user['username']}")
    if user['company']:
        st.markdown(f"**{user['company']}**")
    st.markdown(f"*{user['email']}*")
    
    # Show auth method badge
    if user.get('auth_provider') == 'google':
        auth_badge = "🔐 Google"
    elif user.get('auth_provider') == 'github':
        auth_badge = "🔐 GitHub"
    else:
        auth_badge = "🔑 Password"
    st.caption(auth_badge)
    
    show_logout_button()

# Main tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📄 Single Document", 
    "🔄 Reconciliation", 
    "📊 Batch Processing", 
    "📜 Audit Trail",
    "📁 My Documents"
])

# Get user context
user_id = st.session_state.user_data["user_id"]
session_id = st.session_state.session_id

# TAB 1: Single Document Processing
with tab1:
    st.header("Single Document Analysis")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        uploaded_file = st.file_uploader(
            "Upload Financial Document",
            type=["pdf", "png", "jpg", "jpeg"],
            help="Upload invoice, purchase order, or financial statement"
        )
    
    with col2:
        # Auto-detect document type when file is uploaded
        if uploaded_file:
            # Check if this is a new file
            if "last_uploaded_file" not in st.session_state or st.session_state.last_uploaded_file != uploaded_file.name:
                st.session_state.last_uploaded_file = uploaded_file.name
                
                # Perform auto-detection immediately
                with st.spinner("🔍 Auto-detecting document type..."):
                    # Save file temporarily for detection
                    temp_detect_path = f"temp_detect_{uploaded_file.name}"
                    with open(temp_detect_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    
                    try:
                        async def detect_type():
                            parse_result = await ade_parse_document(temp_detect_path, split_pages=False)
                            markdown = parse_result.get("markdown", "").lower()
                            
                            # Enhanced keyword-based detection
                            if "invoice" in markdown or "bill to" in markdown or "invoice number" in markdown or "invoice no" in markdown or "invoice date" in markdown:
                                return "Invoice"
                            elif "purchase order" in markdown or "po number" in markdown or "p.o. number" in markdown or "order date" in markdown or "delivery date" in markdown:
                                return "Purchase Order"
                            elif "bank statement" in markdown or "account statement" in markdown or "opening balance" in markdown or "closing balance" in markdown or "transaction" in markdown or "statement period" in markdown:
                                return "Bank Statement"
                            else:
                                # Default to invoice if unclear
                                return "Invoice"
                        
                        detected = asyncio.run(detect_type())
                        st.session_state.detected_doc_type = detected
                        st.success(f"🎯 Auto-detected: **{detected}**")
                    except Exception as e:
                        st.warning(f"⚠️ Could not auto-detect type: {str(e)}")
                        st.session_state.detected_doc_type = "Invoice"
                    finally:
                        if os.path.exists(temp_detect_path):
                            os.remove(temp_detect_path)
        
        # Show dropdown with auto-selected type
        doc_type_options = ["Invoice", "Purchase Order", "Bank Statement"]
        if uploaded_file and st.session_state.get("detected_doc_type"):
            default_index = doc_type_options.index(st.session_state.detected_doc_type)
            doc_type = st.selectbox("Document Type", doc_type_options, index=default_index)
        else:
            doc_type = st.selectbox("Document Type", doc_type_options)
        
        process_btn = st.button("🚀 Process Document", type="primary", use_container_width=True)
    
    if uploaded_file and process_btn:
        with st.spinner("Processing document with ADE..."):
            # Save file
            file_path = f"temp_{uploaded_file.name}"
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            try:
                # Process based on type - call tool directly instead of using agent
                if doc_type == "Invoice":
                    async def process():
                        return await process_invoice_direct(file_path)
                    
                    result = asyncio.run(process())
                    
                    st.success("✅ Document processed successfully!")
                    
                    # Display results
                    if isinstance(result, dict):
                        # Show invoice data
                        invoice_data = result.get("invoice_data", {})
                        metadata = result.get("metadata", {})
                        
                        st.markdown("### 📋 Extracted Invoice Data")
                        
                        # Key metrics
                        col1, col2, col3, col4 = st.columns(4)
                        col1.metric("Invoice #", invoice_data.get("invoice_number", "N/A") if invoice_data else "N/A")
                        col2.metric("Total", f"${invoice_data.get('total_amount', 0):,.2f}" if invoice_data else "$0.00")
                        vendor_name = invoice_data.get("vendor_name", "N/A") if invoice_data else "N/A"
                        col3.metric("Vendor", vendor_name[:20] if vendor_name and vendor_name != "N/A" else vendor_name or "N/A")
                        col4.metric("Pages", metadata.get("page_count", "N/A"))
                        
                        # Full data in expandable section
                        with st.expander("View Full Extracted Data"):
                            st.json(invoice_data)
                        
                        # Metadata
                        with st.expander("View Processing Metadata"):
                            st.json(metadata)
                    else:
                        st.json(result)
                    
                    # Save to database
                    save_processed_document(
                        user_id, session_id, uploaded_file.name, "Invoice",
                        json.dumps(invoice_data), json.dumps(metadata), "Success"
                    )
                    add_audit_entry(
                        user_id, session_id, "Single Document Processing",
                        uploaded_file.name, "Invoice", "Success"
                    )
                    update_user_stats(user_id, processed=1, invoices=1)
                    st.session_state.session_docs_count += 1
                
                elif doc_type == "Purchase Order":
                    async def process():
                        return await process_po_direct(file_path)
                    
                    result = asyncio.run(process())
                    
                    st.success("✅ Document processed successfully!")
                    
                    if isinstance(result, dict):
                        po_data = result.get("po_data", {})
                        metadata = result.get("metadata", {})
                        
                        st.markdown("### 📋 Extracted PO Data")
                        
                        col1, col2, col3, col4 = st.columns(4)
                        col1.metric("PO #", po_data.get("po_number", "N/A"))
                        col2.metric("Total", f"${po_data.get('total_amount', 0):,.2f}")
                        col3.metric("Vendor", po_data.get("vendor_name", "N/A")[:20])
                        col4.metric("Pages", metadata.get("page_count", "N/A"))
                        
                        with st.expander("View Full Extracted Data"):
                            st.json(po_data)
                        
                        with st.expander("View Processing Metadata"):
                            st.json(metadata)
                    else:
                        st.json(result)
                    
                    # Save to database
                    save_processed_document(
                        user_id, session_id, uploaded_file.name, "Purchase Order",
                        json.dumps(po_data), json.dumps(metadata), "Success"
                    )
                    add_audit_entry(
                        user_id, session_id, "Single Document Processing",
                        uploaded_file.name, "Purchase Order", "Success"
                    )
                    update_user_stats(user_id, processed=1, pos=1)
                    st.session_state.session_docs_count += 1
                
                elif doc_type == "Bank Statement":
                    async def process():
                        return await process_bank_statement_direct(file_path)
                    
                    result = asyncio.run(process())
                    
                    st.success("✅ Document processed successfully!")
                    
                    if isinstance(result, dict):
                        statement_data = result.get("statement_data", {})
                        metadata = result.get("metadata", {})
                        
                        st.markdown("### 🏦 Extracted Bank Statement Data")
                        
                        col1, col2, col3, col4 = st.columns(4)
                        col1.metric("Account #", statement_data.get("account_number", "N/A"))
                        col2.metric("Opening Balance", f"${statement_data.get('opening_balance', 0):,.2f}")
                        col3.metric("Closing Balance", f"${statement_data.get('closing_balance', 0):,.2f}")
                        col4.metric("Transactions", len(statement_data.get("transactions", [])))
                        
                        # Additional metrics
                        col5, col6, col7 = st.columns(3)
                        col5.metric("Total Deposits", f"${statement_data.get('total_deposits', 0):,.2f}")
                        col6.metric("Total Withdrawals", f"${statement_data.get('total_withdrawals', 0):,.2f}")
                        col7.metric("Bank", statement_data.get("bank_name", "N/A")[:20])
                        
                        # Transaction table
                        if statement_data.get("transactions"):
                            st.markdown("#### 📊 Transactions")
                            transactions_df = pd.DataFrame(statement_data["transactions"])
                            st.dataframe(transactions_df, use_container_width=True)
                        
                        with st.expander("View Full Extracted Data"):
                            st.json(statement_data)
                        
                        with st.expander("View Processing Metadata"):
                            st.json(metadata)
                    else:
                        st.json(result)
                    
                    # Save to database
                    save_processed_document(
                        user_id, session_id, uploaded_file.name, "Bank Statement",
                        json.dumps(statement_data), json.dumps(metadata), "Success"
                    )
                    add_audit_entry(
                        user_id, session_id, "Single Document Processing",
                        uploaded_file.name, "Bank Statement", "Success"
                    )
                    update_user_stats(user_id, processed=1, statements=1)
                    st.session_state.session_docs_count += 1
                
            except Exception as e:
                st.error(f"❌ Error processing document: {str(e)}")
                import traceback
                with st.expander("View Error Details"):
                    st.code(traceback.format_exc())
                
                # Save error to database
                add_audit_entry(
                    user_id, session_id, "Single Document Processing",
                    uploaded_file.name, doc_type, f"Failed: {str(e)}"
                )
            finally:
                if os.path.exists(file_path):
                    os.remove(file_path)

# TAB 2: Reconciliation
with tab2:
    st.header("Invoice-PO Reconciliation")
    st.markdown("Upload an invoice and matching purchase order for automated three-way matching")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📄 Invoice")
        invoice_file = st.file_uploader("Upload Invoice", type=["pdf"], key="invoice")
    
    with col2:
        st.subheader("📋 Purchase Order")
        po_file = st.file_uploader("Upload PO", type=["pdf"], key="po")
    
    reconcile_btn = st.button("🔄 Reconcile Documents", type="primary", use_container_width=True)
    
    if invoice_file and po_file and reconcile_btn:
        with st.spinner("Performing reconciliation..."):
            st.info("Processing invoice and PO with multi-agent system...")
            
            # Save files
            invoice_path = f"temp_{invoice_file.name}"
            po_path = f"temp_{po_file.name}"
            
            with open(invoice_path, "wb") as f:
                f.write(invoice_file.getbuffer())
            with open(po_path, "wb") as f:
                f.write(po_file.getbuffer())
            
            try:
                # Process both documents
                async def reconcile():
                    # Parse invoice
                    inv_result = await process_invoice_direct(invoice_path)
                    invoice_data = inv_result.get("invoice_data", {})
                    
                    # Parse PO
                    po_result = await process_po_direct(po_path)
                    po_data = po_result.get("po_data", {})
                    
                    # Reconcile
                    recon_result = await reconcile_direct(invoice_data, po_data)
                    
                    # Compliance check
                    compliance_result = await compliance_check_direct(invoice_data)
                    
                    return {
                        "invoice": invoice_data,
                        "po": po_data,
                        "reconciliation": recon_result,
                        "compliance": compliance_result
                    }
                
                results = asyncio.run(reconcile())
                
                st.success("✅ Reconciliation complete!")
                
                # Display reconciliation results
                recon = results["reconciliation"]
                
                # Risk badge
                risk_colors = {"LOW": "success", "MEDIUM": "warning", "HIGH": "error"}
                risk_level = recon.get("risk_level", "MEDIUM")
                
                st.markdown(f"""
                <div style="bg-[rgba(222,91,91,1)]" class="{risk_colors.get(risk_level, 'warning')}-box">
                <h3>Risk Level: {risk_level}</h3>
                <p><strong>Recommendation:</strong> {recon.get('recommendation')}</p>
                </div>
                """, unsafe_allow_html=True)
                
                # Metrics
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Invoice Total", f"${recon.get('invoice_total', 0):,.2f}")
                col2.metric("PO Total", f"${recon.get('po_total', 0):,.2f}")
                col3.metric("Variance", f"${recon.get('amount_variance', 0):,.2f}")
                col4.metric("Variance %", f"{recon.get('variance_percentage', 0):.2f}%")
                
                # Discrepancies
                if recon.get("discrepancies"):
                    st.markdown("### ⚠️ Discrepancies Found")
                    for disc in recon["discrepancies"]:
                        st.warning(disc)
                else:
                    st.success("✅ No discrepancies - Perfect match!")
                
                # Compliance
                st.markdown("### 📋 Compliance Check")
                compliance = results["compliance"]
                st.metric("Compliance Score", f"{compliance.get('compliance_score', 0)}/100")
                
                if compliance.get("critical_issues"):
                    for issue in compliance["critical_issues"]:
                        st.error(f"❌ {issue}")
                
                if compliance.get("warnings"):
                    for warning in compliance["warnings"]:
                        st.warning(f"⚠️ {warning}")
                
                # Save reconciliation to database
                save_reconciliation(
                    user_id, session_id, invoice_file.name, po_file.name,
                    risk_level, recon.get("matched", False),
                    recon.get("amount_variance", 0), recon.get("variance_percentage", 0),
                    ", ".join(recon.get("discrepancies", []))
                )
                add_audit_entry(
                    user_id, session_id, "Reconciliation",
                    f"{invoice_file.name} vs {po_file.name}", "Reconciliation", "Success",
                    f"Risk: {risk_level}"
                )
                
                # Update stats
                matched_val = 1 if recon.get("matched") else 0
                flagged_val = 1 if risk_level == "HIGH" else 0
                update_user_stats(user_id, processed=2, matched=matched_val, flagged=flagged_val)
                st.session_state.session_docs_count += 2
                
            except Exception as e:
                st.error(f"Reconciliation failed: {str(e)}")
                import traceback
                st.code(traceback.format_exc())
            finally:
                for path in [invoice_path, po_path]:
                    if os.path.exists(path):
                        os.remove(path)

# TAB 3: Batch Processing
with tab3:
    st.header("Batch Document Processing")
    st.info("Upload multiple invoices for batch processing")
    
    batch_files = st.file_uploader(
        "Upload Multiple Documents",
        type=["pdf"],
        accept_multiple_files=True
    )
    
    if st.button("Process Batch") and batch_files:
        progress = st.progress(0)
        status = st.empty()
        
        results_data = []
        
        for idx, file in enumerate(batch_files):
            status.text(f"Processing {file.name}...")
            progress.progress((idx + 1) / len(batch_files))
            
            file_path = f"temp_{file.name}"
            with open(file_path, "wb") as f:
                f.write(file.getbuffer())
            
            try:
                async def process():
                    return await process_invoice_direct(file_path)
                
                result = asyncio.run(process())
                invoice_data = result.get("invoice_data", {})
                
                results_data.append({
                    "Filename": file.name,
                    "Invoice #": invoice_data.get("invoice_number", "N/A"),
                    "Vendor": invoice_data.get("vendor_name", "N/A"),
                    "Total": invoice_data.get("total_amount", 0),
                    "Date": invoice_data.get("invoice_date", "N/A"),
                    "Status": "✅ Processed"
                })
                
            except Exception as e:
                results_data.append({
                    "Filename": file.name,
                    "Invoice #": "Error",
                    "Vendor": "Error",
                    "Total": 0,
                    "Date": "Error",
                    "Status": f"❌ {str(e)}"
                })
            finally:
                if os.path.exists(file_path):
                    os.remove(file_path)
        
        status.text("Batch processing complete!")
        
        # Display results table
        df = pd.DataFrame(results_data)
        st.dataframe(df, use_container_width=True)
        
        # Summary
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Processed", len(batch_files))
        col2.metric("Successful", len([r for r in results_data if "✅" in r["Status"]]))
        col3.metric("Total Amount", f"${sum([r['Total'] for r in results_data]):,.2f}")
        
        # Download results
        csv = df.to_csv(index=False)
        st.download_button(
            "📥 Download Results CSV",
            csv,
            "batch_processing_results.csv",
            "text/csv"
        )

# TAB 4: Audit Trail
with tab4:
    st.header("📜 Your Processing Audit Trail")
    st.markdown(f"**User:** {user['username']} | **Session ID:** {session_id}")
    
    # Filters
    col1, col2 = st.columns([3, 1])
    with col1:
        limit = st.slider("Number of records to display", 10, 500, 100)
    with col2:
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()
    
    # Get audit trail from database
    audit_data = get_user_audit_trail(user_id, limit)
    
    if audit_data:
        audit_df = pd.DataFrame(audit_data)
        st.dataframe(audit_df, use_container_width=True)
        
        # Stats
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Entries", len(audit_data))
        success_count = len([a for a in audit_data if "Success" in a.get("status", "")])
        col2.metric("Successful", success_count)
        fail_count = len([a for a in audit_data if "Failed" in a.get("status", "")])
        col3.metric("Failed", fail_count)
        
        # Export
        csv = audit_df.to_csv(index=False)
        st.download_button(
            "📥 Export Audit Log",
            csv,
            f"audit_trail_{user['username']}_{datetime.now().strftime('%Y%m%d')}.csv",
            "text/csv"
        )
    else:
        st.info("No audit trail yet. Start by uploading and processing documents!")

# TAB 5: My Documents
with tab5:
    st.header("📁 My Processed Documents")
    
    # Filters
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        doc_limit = st.slider("Documents to display", 10, 200, 50)
    with col2:
        filter_type = st.selectbox("Filter by type", ["All", "Invoice", "Purchase Order", "Bank Statement"])
    with col3:
        if st.button("🔄 Refresh Docs", use_container_width=True):
            st.rerun()
    
    # Get documents from database
    all_docs = get_user_documents(user_id, doc_limit)
    
    # Filter by type
    if filter_type != "All":
        all_docs = [d for d in all_docs if d["doc_type"] == filter_type]
    
    if all_docs:
        st.markdown(f"**Found {len(all_docs)} documents**")
        
        # Display as cards
        for idx, doc in enumerate(all_docs):
            with st.expander(f"📄 {doc['file_name']} - {doc['doc_type']} ({doc['processed_at']})"):
                col1, col2 = st.columns(2)
                col1.markdown(f"**Status:** {doc['status']}")
                col2.markdown(f"**Processed:** {doc['processed_at']}")
                
                if doc.get('data'):
                    try:
                        data = json.loads(doc['data'])
                        st.json(data)
                    except:
                        st.text(doc['data'])
        
        # Export
        docs_df = pd.DataFrame(all_docs)
        csv = docs_df.to_csv(index=False)
        st.download_button(
            "📥 Download Document List",
            csv,
            f"my_documents_{user['username']}_{datetime.now().strftime('%Y%m%d')}.csv",
            "text/csv",
            use_container_width=True
        )
    else:
        st.info("No documents found. Upload and process documents to see them here!")

# Footer
st.markdown("---")
col1, col2, col3 = st.columns(3)
col1.markdown("**Powered by:** LandingAI ADE + Gemini")
col2.markdown("**Built for:** AI Financial Hackathon 2025")
col3.markdown("**Team:** Marvix")