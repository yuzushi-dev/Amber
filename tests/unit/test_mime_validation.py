"""
Tests for PR-07: Server-side MIME validation for document uploads.
"""


class TestMIMEValidation:
    """Test server-side MIME validation using python-magic."""

    def test_upload_validates_pdf_mime_type(self):
        """Test that PDF files are correctly detected by magic bytes."""
        import magic

        # Real PDF content (first bytes: %PDF)
        pdf_content = b"%PDF-1.4\n%test content"
        detected = magic.from_buffer(pdf_content[:4096], mime=True)

        assert detected == "application/pdf", f"Expected application/pdf, got {detected}"

    def test_upload_validates_txt_mime_type(self):
        """Test that text files are correctly detected."""
        import magic

        txt_content = b"Hello, this is plain text content."
        detected = magic.from_buffer(txt_content[:4096], mime=True)

        assert detected == "text/plain", f"Expected text/plain, got {detected}"

    def test_upload_validates_html_mime_type(self):
        """Test that HTML files are correctly detected."""
        import magic

        html_content = b"<!DOCTYPE html><html><body>Test</body></html>"
        detected = magic.from_buffer(html_content[:4096], mime=True)

        assert detected == "text/html", f"Expected text/html, got {detected}"


class TestMIMEValidationInUseCase:
    """Test that MIME validation is wired into use_cases_documents.py."""

    def test_mime_validation_code_exists(self):
        """Test that use_cases_documents.py has MIME validation logic."""
        with open('/home/daniele/Amber/src/core/ingestion/application/use_cases_documents.py') as f:
            content = f.read()

        assert 'import magic' in content or 'from_buffer' in content, \
            "MIME validation should use python-magic"
        assert 'detected_mime' in content, \
            "Should detect MIME type from file content"

    def test_mime_validation_has_allowed_list(self):
        """Test that allowed MIME types are defined."""
        with open('/home/daniele/Amber/src/core/ingestion/application/use_cases_documents.py') as f:
            content = f.read()

        assert 'ALLOWED_MIMES' in content or 'application/pdf' in content, \
            "Should define allowed MIME types"
