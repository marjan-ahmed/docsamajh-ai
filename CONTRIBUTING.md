# Contributing to FinDoc AI Pro

Thank you for your interest in contributing to FinDoc AI Pro! This document provides guidelines and instructions for contributing to the project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [How to Contribute](#how-to-contribute)
- [Coding Standards](#coding-standards)
- [Testing Guidelines](#testing-guidelines)
- [Submitting Changes](#submitting-changes)
- [Issue Reporting](#issue-reporting)
- [Feature Requests](#feature-requests)

## Code of Conduct

### Our Pledge

We are committed to providing a welcoming and inclusive environment for all contributors. We expect all participants to:

- Use welcoming and inclusive language
- Be respectful of differing viewpoints and experiences
- Gracefully accept constructive criticism
- Focus on what is best for the community
- Show empathy towards other community members

## Getting Started

1. **Fork the Repository**
   ```bash
   # Click the "Fork" button on GitHub
   # Then clone your fork
   git clone https://github.com/YOUR-USERNAME/docsamajh.git
   cd docsamajh
   ```

2. **Set Up Development Environment**
   ```bash
   # Create virtual environment
   python -m venv .venv
   
   # Activate (Windows)
   .venv\Scripts\activate
   
   # Activate (Linux/Mac)
   source .venv/bin/activate
   
   # Install dependencies
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables**
   ```bash
   # Copy example environment file
   copy .env.example .env
   
   # Edit .env with your API keys
   # LANDING_AI_API_KEY=your_key_here
   # GOOGLE_API_KEY=your_key_here
   ```

## Development Setup

### Prerequisites

- Python 3.11 or higher
- Git
- A code editor (VS Code recommended)
- LandingAI API key ([Get one here](https://landing.ai))
- Google AI API key ([Get one here](https://aistudio.google.com))

### Recommended VS Code Extensions

- Python (Microsoft)
- Pylance
- Python Debugger
- Black Formatter
- isort
- GitLens

### Project Structure

```
docsamajh/
├── src/
│   └── docsamajh/
│       ├── __init__.py
│       ├── main.py          # Legacy simple chatbot
│       └── app.py           # Main Streamlit application
├── tests/                   # Test files (to be created)
├── docs/                    # Additional documentation
├── .env.example             # Environment template
├── pyproject.toml           # Project configuration
├── requirements.txt         # Python dependencies
└── README.md                # Project overview
```

## How to Contribute

### Types of Contributions

We welcome various types of contributions:

1. **Bug Fixes** - Fix issues and improve stability
2. **Feature Development** - Add new capabilities
3. **Documentation** - Improve guides, comments, and examples
4. **Testing** - Add unit tests and integration tests
5. **Performance** - Optimize code and reduce latency
6. **UI/UX** - Enhance user interface and experience

### Contribution Workflow

1. **Find or Create an Issue**
   - Check existing issues for tasks
   - Create a new issue for bugs or features
   - Wait for maintainer approval before starting work

2. **Create a Branch**
   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/bug-description
   ```

3. **Make Your Changes**
   - Write clean, documented code
   - Follow coding standards (see below)
   - Add tests for new features
   - Update documentation as needed

4. **Test Your Changes**
   ```bash
   # Run the application
   streamlit run src/docsamajh/app.py
   
   # Run tests (when available)
   pytest tests/
   ```

5. **Commit Your Changes**
   ```bash
   git add .
   git commit -m "feat: add invoice validation feature"
   ```

6. **Push and Create Pull Request**
   ```bash
   git push origin feature/your-feature-name
   # Then create a Pull Request on GitHub
   ```

## Coding Standards

### Python Style Guide

We follow PEP 8 with some modifications:

- **Line Length**: 100 characters (not 79)
- **Indentation**: 4 spaces (no tabs)
- **Quotes**: Use double quotes for strings
- **Imports**: Organize with isort

### Code Formatting

```bash
# Format code with Black
black src/

# Sort imports
isort src/

# Type checking (if using mypy)
mypy src/
```

### Naming Conventions

```python
# Functions and variables: snake_case
def process_invoice_data():
    total_amount = 0

# Classes: PascalCase
class InvoiceProcessor:
    pass

# Constants: UPPER_SNAKE_CASE
MAX_FILE_SIZE = 10485760

# Private methods: _leading_underscore
def _internal_helper():
    pass
```

### Documentation

All functions should have docstrings:

```python
async def ade_extract_data(markdown_content: str, schema: dict, doc_type: str) -> dict:
    """
    Extract structured data from markdown using LandingAI ADE Extract API.
    
    Args:
        markdown_content (str): Markdown text from Parse API
        schema (dict): JSON schema defining expected structure
        doc_type (str): Document type (invoice, po, receipt)
    
    Returns:
        dict: Extracted structured data matching schema
    
    Raises:
        Exception: If API call fails or returns non-200 status
    """
    # Implementation...
```

### Async/Await Guidelines

- Use `async`/`await` for I/O operations (API calls, file operations)
- Don't mix sync and async code unnecessarily
- Use `asyncio.gather()` for parallel operations
- Handle exceptions properly in async contexts

```python
# Good
async def process_documents(files):
    tasks = [process_single_doc(f) for f in files]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results

# Avoid blocking calls in async functions
async def bad_example():
    time.sleep(5)  # Bad! Use await asyncio.sleep(5)
```

## Testing Guidelines

### Test Structure

```python
# tests/test_ade_integration.py
import pytest
from docsamajh.app import ade_parse_document, ade_extract_data

@pytest.mark.asyncio
async def test_parse_invoice():
    """Test invoice parsing with sample PDF."""
    with open("tests/fixtures/sample_invoice.pdf", "rb") as f:
        result = await ade_parse_document(f.read())
    
    assert result["status"] == "success"
    assert len(result["markdown"]) > 0

@pytest.mark.asyncio
async def test_extract_invoice_data():
    """Test data extraction from parsed invoice."""
    markdown = "Invoice #: INV-001\nTotal: $1,550.00"
    result = await ade_extract_data(markdown, INVOICE_SCHEMA, "invoice")
    
    assert result["invoice_number"] == "INV-001"
    assert result["total_amount"] == 1550.00
```

### Running Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov

# Run all tests
pytest

# Run with coverage
pytest --cov=src/docsamajh --cov-report=html

# Run specific test file
pytest tests/test_ade_integration.py

# Run tests matching pattern
pytest -k "test_parse"
```

## Submitting Changes

### Pull Request Checklist

Before submitting a PR, ensure:

- [ ] Code follows style guidelines
- [ ] All tests pass
- [ ] New features have tests
- [ ] Documentation is updated
- [ ] Commit messages are clear and descriptive
- [ ] No merge conflicts with main branch
- [ ] Large files are not committed
- [ ] API keys are not in code

### Commit Message Format

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting)
- `refactor`: Code refactoring
- `test`: Adding tests
- `chore`: Maintenance tasks

**Examples:**
```bash
feat(reconciliation): add 3-way matching algorithm

Implemented invoice-PO-receipt matching with risk scoring.
Supports tolerance levels and flagging mismatches.

Closes #23

---

fix(ui): handle null values in vendor name display

Added null checks before slicing vendor names to prevent
TypeError when ADE returns partial data.

Fixes #45

---

docs(readme): update installation instructions

Added Python 3.11+ requirement and clarified API key setup.
```

### Pull Request Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Performance improvement
- [ ] Refactoring

## Testing
How was this tested?

## Screenshots (if applicable)
Add screenshots for UI changes

## Checklist
- [ ] Tests pass
- [ ] Documentation updated
- [ ] Code follows style guide
- [ ] No API keys in code
```

## Issue Reporting

### Bug Reports

When reporting bugs, include:

1. **Description**: Clear description of the bug
2. **Steps to Reproduce**: Exact steps to trigger the issue
3. **Expected Behavior**: What should happen
4. **Actual Behavior**: What actually happens
5. **Environment**: Python version, OS, dependencies
6. **Screenshots**: If applicable
7. **Error Messages**: Full error traceback

**Template:**
```markdown
### Bug Description
App crashes when uploading PDF larger than 5MB

### Steps to Reproduce
1. Go to "Single Document Processing" tab
2. Upload 6MB invoice PDF
3. Click "Process Document"
4. Error appears

### Expected Behavior
Document should be processed or show file size warning

### Actual Behavior
TypeError: 'NoneType' object is not subscriptable

### Environment
- Python: 3.13.0
- OS: Windows 11
- Streamlit: 1.44.0

### Error Message
```
Traceback (most recent call last):
  File "app.py", line 633
  ...
```
```

## Feature Requests

### Suggesting Features

When requesting features, include:

1. **Problem Statement**: What problem does this solve?
2. **Proposed Solution**: How should it work?
3. **Use Cases**: Real-world scenarios
4. **Alternatives**: Other solutions considered
5. **Additional Context**: Mockups, examples, references

**Template:**
```markdown
### Feature Request: Multi-Currency Support

**Problem:**
Currently, the app only handles USD amounts. Many businesses 
process international invoices in EUR, GBP, JPY, etc.

**Proposed Solution:**
Add currency detection and conversion:
- Auto-detect currency from document
- Convert to USD for reconciliation
- Support configurable exchange rates

**Use Cases:**
- Global companies with multi-currency vendors
- Import/export businesses
- International service providers

**Alternatives Considered:**
- Manual currency field entry (too slow)
- Pre-conversion before upload (error-prone)

**Additional Context:**
Could integrate with API like exchangerate-api.com
```

## Development Best Practices

### Security

- **Never commit API keys** - Use `.env` files
- **Validate all inputs** - Sanitize user data
- **Use secure dependencies** - Keep packages updated
- **Handle errors gracefully** - Don't expose internals

### Performance

- **Async for I/O** - Use async/await for API calls
- **Batch operations** - Process multiple files together
- **Cache results** - Store session state appropriately
- **Optimize queries** - Minimize API calls

### Code Quality

- **Keep functions small** - Single responsibility principle
- **Avoid duplication** - DRY (Don't Repeat Yourself)
- **Use type hints** - Help with IDE support
- **Comment complex logic** - Explain the "why", not "what"

## Getting Help

### Communication Channels

- **GitHub Issues**: Bug reports and feature requests
- **Discussions**: Questions and community support
- **Email**: [your-email@example.com] for sensitive issues

### Resources

- [LandingAI Documentation](https://landing.ai/docs)
- [Streamlit Documentation](https://docs.streamlit.io)
- [Google AI Studio](https://ai.google.dev)
- [Python Asyncio Guide](https://docs.python.org/3/library/asyncio.html)

## Recognition

Contributors will be recognized in:

- README.md Contributors section
- Release notes for significant contributions
- GitHub contributors page

## License

By contributing, you agree that your contributions will be licensed under the same license as the project (MIT License).

---

## Quick Start for Contributors

```bash
# 1. Fork and clone
git clone https://github.com/YOUR-USERNAME/docsamajh.git
cd docsamajh

# 2. Set up environment
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt

# 3. Create branch
git checkout -b feature/amazing-feature

# 4. Make changes and test
streamlit run src/docsamajh/app.py

# 5. Commit and push
git add .
git commit -m "feat: add amazing feature"
git push origin feature/amazing-feature

# 6. Create Pull Request on GitHub
```

## Thank You! 🎉

Your contributions make FinDoc AI Pro better for everyone. We appreciate your time and effort!

For questions or guidance, feel free to open a discussion or reach out to the maintainers.

Happy coding! 🚀
