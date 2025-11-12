# 🚀 Deployment & Testing Guide

## DocSamajh AI - Production Deployment

---

## 📋 Table of Contents

1. [Quick Start](#quick-start)
2. [Testing](#testing)
3. [Deployment Options](#deployment-options)
4. [Production Configuration](#production-configuration)
5. [Monitoring & Maintenance](#monitoring--maintenance)
6. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Local Development

```bash
# 1. Clone repository
git clone https://github.com/yourusername/findoc-ai-pro.git
cd findoc-ai-pro

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your API keys

# 5. Run application
streamlit run src/docsamajh/app.py

# 6. Open browser
# http://localhost:8501
```

---

## Testing

### Unit Tests

Create `tests/test_reconciliation.py`:

```python
import pytest
from src.docsamajh.app import reconcile_invoice_to_po

@pytest.mark.asyncio
async def test_perfect_match():
    invoice_data = {
        "vendor_name": "Acme Corp",
        "total_amount": 1000.00,
        "line_items": [
            {"description": "Widget A", "quantity": 10, "unit_price": 100}
        ]
    }
    
    po_data = {
        "vendor_name": "Acme Corp",
        "total_amount": 1000.00,
        "line_items": [
            {"description": "Widget A", "quantity": 10, "unit_price": 100}
        ]
    }
    
    result = await reconcile_invoice_to_po(invoice_data, po_data)
    
    assert result["matched"] == True
    assert result["risk_level"] == "LOW"
    assert len(result["discrepancies"]) == 0

@pytest.mark.asyncio
async def test_amount_variance():
    invoice_data = {
        "vendor_name": "Acme Corp",
        "total_amount": 1100.00,
        "line_items": []
    }
    
    po_data = {
        "vendor_name": "Acme Corp",
        "total_amount": 1000.00,
        "line_items": []
    }
    
    result = await reconcile_invoice_to_po(invoice_data, po_data)
    
    assert result["matched"] == False
    assert result["amount_variance"] == 100.00
    assert result["risk_level"] in ["MEDIUM", "HIGH"]
```

Run tests:
```bash
pytest tests/ -v
```

### Integration Tests

```python
# tests/test_ade_integration.py
import pytest
from src.docsamajh.app import ade_parse_document, ade_extract_data

@pytest.mark.asyncio
async def test_parse_invoice():
    result = await ade_parse_document("sample_invoice.pdf")
    
    assert "markdown" in result
    assert "metadata" in result
    assert len(result["markdown"]) > 0

@pytest.mark.asyncio
async def test_extract_invoice_data():
    markdown = "Invoice #123\nVendor: Acme\nTotal: $1,000.00"
    
    schema = {
        "type": "object",
        "properties": {
            "invoice_number": {"type": "string"},
            "total": {"type": "number"}
        }
    }
    
    result = await ade_extract_data(markdown, schema)
    
    assert "extraction" in result
    assert result["extraction"]["invoice_number"] == "123"
```

### Manual Testing Checklist

**Single Document Processing:**
- [ ] Upload valid invoice PDF
- [ ] Upload invalid file (should show error)
- [ ] Verify all fields extracted correctly
- [ ] Check metadata is captured
- [ ] Confirm processing under 10 seconds

**Reconciliation:**
- [ ] Upload matching invoice + PO (should be LOW risk)
- [ ] Upload mismatched documents (should be HIGH risk)
- [ ] Verify discrepancies are listed
- [ ] Check compliance score is calculated
- [ ] Confirm recommendation makes sense

**Batch Processing:**
- [ ] Upload 10 invoices
- [ ] Verify progress bar works
- [ ] Check all results appear in table
- [ ] Download CSV and verify format
- [ ] Test with mixed valid/invalid files

**Audit Trail:**
- [ ] Process some documents
- [ ] Check audit trail populates
- [ ] Export audit log CSV
- [ ] Verify timestamps and statuses

---

## Deployment Options

### Option 1: Streamlit Cloud (Easiest)

1. **Push to GitHub**
   ```bash
   git add .
   git commit -m "Initial commit"
   git push origin main
   ```

2. **Deploy on Streamlit Cloud**
   - Go to https://share.streamlit.io
   - Connect your GitHub repository
   - Select `src/docsamajh/app.py` as main file
   - Add secrets (API keys) in dashboard
   - Click "Deploy"

3. **Configure Secrets**
   In Streamlit Cloud dashboard → Settings → Secrets:
   ```toml
   ADE_API_KEY = "your_key"
   GEMINI_API_KEY = "your_key"
   GEMINI_MODEL = "gemini-2.5-flash"
   BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
   ```

**Pros**: Free, easy, automatic HTTPS
**Cons**: Limited resources, public URL

---

### Option 2: AWS EC2 (Scalable)

1. **Launch EC2 Instance**
   - AMI: Ubuntu 22.04 LTS
   - Instance type: t3.medium (2 vCPU, 4GB RAM)
   - Security group: Allow ports 22, 8501

2. **Setup Application**
   ```bash
   # SSH into instance
   ssh -i your-key.pem ubuntu@your-ec2-ip
   
   # Install dependencies
   sudo apt update
   sudo apt install python3-pip python3-venv -y
   
   # Clone repo
   git clone https://github.com/yourusername/findoc-ai-pro.git
   cd findoc-ai-pro
   
   # Create venv and install
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   
   # Configure environment
   nano .env  # Add your API keys
   ```

3. **Run with systemd (Production)**
   Create `/etc/systemd/system/findoc-ai.service`:
   ```ini
   [Unit]
   Description=DocSamajh AI
   After=network.target
   
   [Service]
   Type=simple
   User=ubuntu
   WorkingDirectory=/home/ubuntu/findoc-ai-pro
   Environment="PATH=/home/ubuntu/findoc-ai-pro/.venv/bin"
   ExecStart=/home/ubuntu/findoc-ai-pro/.venv/bin/streamlit run src/docsamajh/app.py --server.port 8501 --server.address 0.0.0.0
   Restart=always
   
   [Install]
   WantedBy=multi-user.target
   ```
   
   Enable and start:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable findoc-ai
   sudo systemctl start findoc-ai
   sudo systemctl status findoc-ai
   ```

4. **Setup NGINX Reverse Proxy**
   ```bash
   sudo apt install nginx -y
   
   # Create config
   sudo nano /etc/nginx/sites-available/findoc-ai
   ```
   
   ```nginx
   server {
       listen 80;
       server_name your-domain.com;
       
       location / {
           proxy_pass http://localhost:8501;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
           proxy_set_header Host $host;
           proxy_cache_bypass $http_upgrade;
       }
   }
   ```
   
   Enable:
   ```bash
   sudo ln -s /etc/nginx/sites-available/findoc-ai /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl restart nginx
   ```

5. **Setup SSL with Let's Encrypt**
   ```bash
   sudo apt install certbot python3-certbot-nginx -y
   sudo certbot --nginx -d your-domain.com
   ```

**Pros**: Full control, scalable, custom domain
**Cons**: Requires AWS knowledge, manual maintenance

---

### Option 3: Docker Container (Portable)

1. **Create Dockerfile**
   ```dockerfile
   FROM python:3.10-slim
   
   WORKDIR /app
   
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   
   COPY . .
   
   EXPOSE 8501
   
   CMD ["streamlit", "run", "src/docsamajh/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
   ```

2. **Create docker-compose.yml**
   ```yaml
   version: '3.8'
   
   services:
     findoc-ai:
       build: .
       ports:
         - "8501:8501"
       environment:
         - ADE_API_KEY=${ADE_API_KEY}
         - GEMINI_API_KEY=${GEMINI_API_KEY}
         - GEMINI_MODEL=${GEMINI_MODEL}
         - BASE_URL=${BASE_URL}
       volumes:
         - ./data:/app/data
       restart: unless-stopped
   ```

3. **Build and Run**
   ```bash
   docker-compose up -d
   ```

**Pros**: Portable, easy scaling, consistent environment
**Cons**: Requires Docker knowledge

---

## Production Configuration

### Environment Variables

```bash
# Required
ADE_API_KEY=your_landing_ai_key
GEMINI_API_KEY=your_gemini_key

# Optional - Performance
STREAMLIT_SERVER_MAX_UPLOAD_SIZE=200  # MB
STREAMLIT_SERVER_ENABLE_CORS=false
STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=true

# Optional - Caching
STREAMLIT_SERVER_ENABLE_STATIC_SERVING=true
```

### Streamlit Config

Create `.streamlit/config.toml`:

```toml
[server]
port = 8501
enableCORS = false
enableXsrfProtection = true
maxUploadSize = 200

[browser]
gatherUsageStats = false

[theme]
primaryColor = "#1f77b4"
backgroundColor = "#ffffff"
secondaryBackgroundColor = "#f0f2f6"
textColor = "#262730"
font = "sans serif"
```

### Rate Limiting

Add to `app.py`:

```python
import time
from functools import wraps

def rate_limit(max_calls=10, time_window=60):
    calls = []
    
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            now = time.time()
            # Remove old calls
            while calls and calls[0] < now - time_window:
                calls.pop(0)
            
            if len(calls) >= max_calls:
                raise Exception(f"Rate limit exceeded: {max_calls} calls per {time_window}s")
            
            calls.append(now)
            return await func(*args, **kwargs)
        return wrapper
    return decorator

# Apply to ADE calls
@rate_limit(max_calls=20, time_window=60)
async def ade_parse_document(file_path, split_pages=False):
    # ... existing code
```

---

## Monitoring & Maintenance

### Logging

Add comprehensive logging:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('findoc_ai.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Use in functions
logger.info(f"Processing invoice: {filename}")
logger.error(f"ADE API error: {error_message}")
```

### Metrics to Track

- **API Usage**: ADE credits consumed, API call count
- **Processing Time**: Average time per document
- **Success Rate**: % of documents processed successfully
- **Error Types**: Frequency of different errors
- **User Activity**: Documents processed per day/week

### Health Checks

Create `/health` endpoint:

```python
@st.cache_resource
def health_check():
    return {
        "status": "healthy",
        "version": "1.0.0",
        "ade_connected": check_ade_connection(),
        "llm_connected": check_llm_connection()
    }
```

---

## Troubleshooting

### Common Issues

**1. "ADE API error (401): Unauthorized"**
- Check `ADE_API_KEY` in `.env`
- Verify key is valid at https://va.landing.ai/settings/api-key
- Ensure no extra spaces in `.env` file

**2. "Connection timeout"**
- Check internet connection
- Verify ADE endpoints are accessible
- Increase timeout in aiohttp session

**3. "Module 'agents' not found"**
- Install agents framework: `pip install agents`
- Or replace with your agentic library

**4. "File too large"**
- Increase `maxUploadSize` in config.toml
- Compress PDF before uploading
- Use ADE's document_url parameter for large files

**5. "Streamlit app won't start"**
- Check port 8501 is not in use
- Verify all dependencies installed
- Check for syntax errors in app.py

### Debug Mode

Enable detailed logging:

```python
import os
os.environ['STREAMLIT_DEBUG'] = 'true'

# Or run with
streamlit run app.py --logger.level=debug
```

### Performance Optimization

**1. Enable caching**
```python
@st.cache_data(ttl=3600)
def parse_document_cached(file_hash):
    # Cache parsed results for 1 hour
    pass
```

**2. Async batch processing**
```python
import asyncio

async def process_batch(files):
    tasks = [parse_invoice(f) for f in files]
    results = await asyncio.gather(*tasks)
    return results
```

**3. Reduce API calls**
- Cache frequent schemas
- Batch extract requests
- Use ADE's split parameter strategically

---

## Security Best Practices

### API Key Management

❌ **Never commit API keys to Git**
```bash
# Add to .gitignore
.env
*.env
.env.*
```

✅ **Use environment variables**
```python
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("ADE_API_KEY")
```

### File Upload Security

```python
import mimetypes

ALLOWED_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg'}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

def validate_upload(uploaded_file):
    # Check extension
    ext = os.path.splitext(uploaded_file.name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"File type {ext} not allowed")
    
    # Check size
    if uploaded_file.size > MAX_FILE_SIZE:
        raise ValueError("File too large")
    
    # Check MIME type
    mime_type = mimetypes.guess_type(uploaded_file.name)[0]
    if mime_type not in ['application/pdf', 'image/png', 'image/jpeg']:
        raise ValueError("Invalid file type")
```

### Data Privacy

- **Delete temp files** immediately after processing
- **Don't log** sensitive financial data
- **Encrypt** data at rest if storing
- **Use HTTPS** in production
- **Implement** access controls for multi-user

---

## 90-Day Pilot Checklist

### Week 1-4: Setup & Integration

- [ ] Deploy to production environment
- [ ] Configure monitoring and logging
- [ ] Integrate with company ERP (CSV export)
- [ ] Train finance team on UI (2-hour session)
- [ ] Document standard operating procedures
- [ ] Set up weekly check-in meetings

### Week 5-8: Parallel Processing

- [ ] Process 100 invoices in parallel with manual
- [ ] Compare accuracy rates daily
- [ ] Track time savings
- [ ] Collect user feedback via survey
- [ ] Fine-tune reconciliation thresholds
- [ ] Add company-specific validation rules

### Week 9-12: Full Rollout

- [ ] Transition to AI-first processing
- [ ] Manual review only for HIGH risk items
- [ ] Build executive dashboard for metrics
- [ ] Document ROI and cost savings
- [ ] Plan for expansion to other document types
- [ ] Present results to leadership

### Success Criteria

✅ **Accuracy**: >95% match rate with manual review
✅ **Speed**: <30 seconds average processing time
✅ **Adoption**: 80%+ of invoices via AI
✅ **ROI**: $30K+ annual savings demonstrated
✅ **User Satisfaction**: >4/5 rating from AP team

---

## Support

### Documentation
- [README.md](README.md) - Project overview
- [PRESENTATION_GUIDE.md](PRESENTATION_GUIDE.md) - Demo guide
- This file - Deployment guide

### Community
- GitHub Issues: Report bugs
- Discord: #financial-hack-nyc channel
- Email: support@findoc-ai.com (example)

---

**Built for the AI Financial Hackathon Championship 2024**

*Last Updated: November 2024*
