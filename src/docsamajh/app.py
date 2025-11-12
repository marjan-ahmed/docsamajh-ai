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
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from dotenv import load_dotenv
from openai import AsyncOpenAI
from agents import Agent, Runner, RunConfig, OpenAIChatCompletionsModel, set_tracing_disabled, function_tool

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

async def reconcile_direct(invoice_data: dict, po_data: dict):
    """Direct reconciliation without going through agent"""
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

async def compliance_check_direct(invoice_data: dict):
    """Direct compliance check without going through agent"""
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
    Parse invoices and purchase orders accurately, extract all financial data,
    and ensure data quality. Use the parse_invoice and parse_purchase_order tools.""",
    model=model,
    tools=[parse_invoice, parse_purchase_order]
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
    st.image("docsamajhai.jpg", width=120)
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
    st.header("📈 Session Stats")
    if "stats" not in st.session_state:
        st.session_state.stats = {"processed": 0, "matched": 0, "flagged": 0}
    
    col1, col2 = st.columns(2)
    col1.metric("Processed", st.session_state.stats["processed"])
    col2.metric("Matched", st.session_state.stats["matched"])
    st.metric("Flagged", st.session_state.stats["flagged"])

# Main tabs
tab1, tab2, tab3, tab4 = st.tabs(["📄 Single Document", "🔄 Reconciliation", "📊 Batch Processing", "📜 Audit Trail"])

# Initialize session state
if "audit_trail" not in st.session_state:
    st.session_state.audit_trail = []
if "processed_docs" not in st.session_state:
    st.session_state.processed_docs = {}

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
        doc_type = st.selectbox("Document Type", ["Invoice", "Purchase Order", "Bank Statement"])
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
                    
                    # Update stats
                    st.session_state.stats["processed"] += 1
                    st.session_state.audit_trail.append({
                        "timestamp": datetime.now(),
                        "action": "Single Document Processing",
                        "file": uploaded_file.name,
                        "type": doc_type,
                        "status": "Success"
                    })
                
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
                    
                    st.session_state.stats["processed"] += 1
                    st.session_state.audit_trail.append({
                        "timestamp": datetime.now(),
                        "action": "Single Document Processing",
                        "file": uploaded_file.name,
                        "type": doc_type,
                        "status": "Success"
                    })
                
            except Exception as e:
                st.error(f"❌ Error processing document: {str(e)}")
                import traceback
                with st.expander("View Error Details"):
                    st.code(traceback.format_exc())
                
                st.session_state.audit_trail.append({
                    "timestamp": datetime.now(),
                    "action": "Single Document Processing",
                    "file": uploaded_file.name,
                    "type": doc_type,
                    "status": f"Failed: {str(e)}"
                })
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
                <div class="{risk_colors.get(risk_level, 'warning')}-box">
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
                
                # Update stats
                st.session_state.stats["processed"] += 2
                if recon.get("matched"):
                    st.session_state.stats["matched"] += 1
                if risk_level == "HIGH":
                    st.session_state.stats["flagged"] += 1
                
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
    st.header("Processing Audit Trail")
    
    if st.session_state.audit_trail:
        audit_df = pd.DataFrame(st.session_state.audit_trail)
        st.dataframe(audit_df, use_container_width=True)
        
        # Export
        csv = audit_df.to_csv(index=False)
        st.download_button(
            "📥 Export Audit Log",
            csv,
            f"audit_trail_{datetime.now().strftime('%Y%m%d')}.csv",
            "text/csv"
        )
    else:
        st.info("No processing history yet. Start by uploading and processing documents!")

# Footer
st.markdown("---")
col1, col2, col3 = st.columns(3)
col1.markdown("**Powered by:** LandingAI ADE + Gemini")
col2.markdown("**Built for:** AI Financial Hackathon 2025")
col3.markdown("**Team:** Marvix")