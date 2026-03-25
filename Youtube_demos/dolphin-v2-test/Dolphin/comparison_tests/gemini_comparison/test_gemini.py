#!/usr/bin/env python3
"""
Gemini API Comparison Test
Demonstrates the cost implications of using advanced commercial models
for document understanding compared to Dolphin's open-source approach.
"""

import os
import sys
import time
import json
from pathlib import Path
from datetime import datetime
import base64
from typing import List, Dict, Any

try:
    from google import genai
    from google.genai import types
    from PIL import Image
    import requests
except ImportError:
    print("Installing required packages...")
    os.system("pip install google-genai Pillow requests")
    from google import genai
    from google.genai import types
    from PIL import Image
    import requests


class GeminiDocumentProcessor:
    """Gemini-based document processor for comparison testing"""
    
    def __init__(self, api_key: str = None):
        """Initialize Gemini API client
        
        Args:
            api_key: Google API key. If None, reads from GEMINI_API_KEY environment variable
        """
        self.api_key = api_key or os.getenv('GEMINI_API_KEY')
        if not self.api_key:
            raise ValueError(
                "API key required. Set GEMINI_API_KEY environment variable or pass api_key parameter.\n"
                "Get your free API key from: https://aistudio.google.com/app/apikey"
            )
        
        # Initialize new Gemini client
        os.environ['GOOGLE_API_KEY'] = self.api_key
        self.client = genai.Client()
        self.model_name = "gemini-3-flash-preview"
        
        # Updated pricing for Gemini 3 Flash (as of 2026)
        self.pricing = {
            "input_per_1m_tokens": 0.50,   # $0.50 per 1M input tokens (text/image/video)
            "output_per_1m_tokens": 3.00,  # $3.00 per 1M output tokens (including thinking tokens)
            "free_tier_tokens": 1000000    # Free tokens per day
        }
        
    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate API cost based on actual token usage"""
        input_cost = (input_tokens / 1_000_000) * self.pricing["input_per_1m_tokens"]
        output_cost = (output_tokens / 1_000_000) * self.pricing["output_per_1m_tokens"]
        return input_cost + output_cost
    
    def parse_content_to_blocks(self, content: str) -> list:
        """Parse extracted content into blocks similar to Dolphin format"""
        if not content:
            return []
        
        blocks = []
        lines = content.strip().split('\n')
        current_block = ""
        block_type = "para"  # Default type
        
        for line in lines:
            line = line.strip()
            if not line:
                if current_block:
                    blocks.append({
                        "label": block_type,
                        "text": current_block.strip(),
                        "bbox": [0, 0, 0, 0]  # Placeholder bbox
                    })
                    current_block = ""
                    block_type = "para"
                continue
            
            # Detect block types
            if line.startswith('#'):
                block_type = "title"
            elif '|' in line and line.count('|') >= 2:
                block_type = "tab"
            elif line.startswith('$$') or '$' in line:
                block_type = "equ"
            elif line.startswith('```'):
                block_type = "code"
            else:
                block_type = "para"
            
            if current_block:
                current_block += "\n" + line
            else:
                current_block = line
        
        # Add final block
        if current_block:
            blocks.append({
                "label": block_type,
                "text": current_block.strip(),
                "bbox": [0, 0, 0, 0]
            })
        
        return blocks

    def convert_pdf_to_images(self, pdf_path: str) -> List[Image.Image]:
        """Convert PDF to images using fitz (PyMuPDF)"""
        try:
            import fitz  # PyMuPDF
        except ImportError:
            print("Installing PyMuPDF...")
            os.system("pip install PyMuPDF")
            import fitz
        
        images = []
        doc = fitz.open(pdf_path)
        
        for page_num in range(doc.page_count):
            page = doc[page_num]
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x zoom for quality
            img_data = pix.tobytes("png")
            
            # Convert to PIL Image
            from io import BytesIO
            img = Image.open(BytesIO(img_data))
            images.append(img)
            
        doc.close()
        return images

    def process_document(self, file_path: str, output_dir: Path) -> Dict[str, Any]:
        """Process document using Gemini API"""
        
        print(f"Processing {file_path} with Gemini...")
        start_time = time.time()
        
        file_path = Path(file_path)
        file_ext = file_path.suffix.lower()
        
        # Load images
        images = []
        if file_ext == '.pdf':
            print("Converting PDF to images (first 3 pages only)...")
            all_images = self.convert_pdf_to_images(str(file_path))
            images = all_images[:3]  # Only process first 3 pages
        elif file_ext in ['.png', '.jpg', '.jpeg']:
            images = [Image.open(file_path)]
        else:
            raise ValueError(f"Unsupported file type: {file_ext}")
        
        print(f"Processing {len(images)} page(s) (limited to first 3)...")
        
        # Simple OCR extraction prompt like Dolphin
        prompt = """
        Extract all text content from this image. Provide the text exactly as it appears, preserving:
        - Original formatting and layout
        - Tables in markdown format
        - Mathematical formulas using LaTeX notation
        - Headers, paragraphs, and bullet points
        
        Output only the extracted text content without analysis or commentary.
        """
        
        results = []
        total_input_tokens = 0
        total_output_tokens = 0
        
        for page_num, image in enumerate(images, 1):
            print(f"Processing page {page_num}/{len(images)} with Gemini API...")
            
            try:
                # Convert PIL image to bytes
                from io import BytesIO
                img_byte_arr = BytesIO()
                image.save(img_byte_arr, format='PNG')
                img_byte_arr = img_byte_arr.getvalue()
                
                # Create image part
                image_part = types.Part.from_bytes(
                    data=img_byte_arr, 
                    mime_type="image/png"
                )
                
                # Make API call with new client
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=[prompt, image_part],
                )
                
                # Get actual token counts from response
                if hasattr(response, 'usage_metadata') and response.usage_metadata:
                    input_tokens = response.usage_metadata.prompt_token_count
                    output_tokens = response.usage_metadata.candidates_token_count
                else:
                    # Fallback estimation: ~4 chars per token
                    input_tokens = len(prompt) // 4 + 258  # 258 tokens per image
                    output_tokens = len(response.text) // 4 if response.text else 0
                
                total_input_tokens += input_tokens
                total_output_tokens += output_tokens
                
                # Parse content into blocks like Dolphin format
                content = response.text if response.text else ""
                
                page_result = {
                    "page_number": page_num,
                    "content": content,
                    "text_blocks": self.parse_content_to_blocks(content),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "request_successful": True
                }
                
                results.append(page_result)
                
                # Shorter wait for demo
                time.sleep(0.5)
                
            except Exception as e:
                print(f"Error processing page {page_num}: {str(e)}")
                results.append({
                    "page_number": page_num,
                    "content": f"[ERROR: {str(e)}]",
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "request_successful": False
                })
        
        end_time = time.time()
        processing_time = end_time - start_time
        
        # Calculate estimated cost based on actual token usage
        successful_requests = len([r for r in results if not r["content"].startswith("[ERROR")])
        estimated_cost = self.estimate_cost(total_input_tokens, total_output_tokens)
        
        # Compile results
        summary = {
            "file": str(file_path),
            "tool": "gemini-3-flash-preview",
            "processing_time": processing_time,
            "timestamp": datetime.now().isoformat(),
            "total_pages": len(images),
            "pages_processed": len([r for r in results if not r["content"].startswith("[ERROR")]),
            "total_requests": len(images),
            "successful_requests": successful_requests,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "estimated_cost_usd": round(estimated_cost, 6),
            "pricing_info": self.pricing,
            "detailed_results": results
        }
        
        # Save results in Dolphin-like format
        output_file = output_dir / f"{file_path.stem}_gemini_content.md"
        json_file = output_dir / f"{file_path.stem}_gemini_blocks.json"
        
        # Compile all blocks for JSON output
        all_blocks = []
        for result in results:
            if 'text_blocks' in result:
                for block in result['text_blocks']:
                    block['page_number'] = result['page_number']
                    all_blocks.extend([block])
        
        # Save JSON blocks (Dolphin format)
        dolphin_format = {
            "file": str(file_path),
            "tool": "gemini-3-flash-preview",
            "processing_time": processing_time,
            "timestamp": datetime.now().isoformat(),
            "total_pages": len(images),
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "estimated_cost_usd": estimated_cost,
            "pricing_info": self.pricing,
            "blocks": all_blocks
        }
        
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(dolphin_format, f, indent=2, ensure_ascii=False)
        
        # Save clean markdown content (like Dolphin)
        with open(output_file, 'w', encoding='utf-8') as f:
            for result in results:
                if len(images) > 1:
                    f.write(f"# Page {result['page_number']}\n\n")
                f.write(result['content'])
                if result['page_number'] < len(images):
                    f.write("\n\n---\n\n")
        
        print(f"📄 Markdown content saved to {output_file}")
        print(f"📊 JSON blocks saved to {json_file}")
        print(f"🔢 Tokens - Input: {total_input_tokens:,}, Output: {total_output_tokens:,}")
        print(f"💰 Estimated cost: ${estimated_cost:.6f} USD")
        
        return dolphin_format


def main():
    # Check for API key
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        print("❌ GEMINI_API_KEY environment variable not set!")
        print("📝 To run this test:")
        print("   1. Get a free API key from: https://aistudio.google.com/app/apikey")
        print("   2. Set the environment variable:")
        print("      export GEMINI_API_KEY='your-api-key-here'")
        print("   3. Re-run this script")
        print("\n💡 This test is optional - it demonstrates the cost of using commercial APIs")
        print("   compared to Dolphin's free, open-source approach.")
        return

    # Setup paths
    script_dir = Path(__file__).parent
    output_dir = script_dir / "results"
    output_dir.mkdir(exist_ok=True)
    
    # Find specific test files as requested
    demo_dir = Path(__file__).parent.parent.parent / "demo"
    
    # Look for exact files: page_0.jpeg, page_1.png, page_2.jpeg
    target_files = [
        "page_0.jpeg",
        "page_1.png", 
        "page_2.jpeg"
    ]
    
    test_files = []
    for target_file in target_files:
        found = False
        for img_file in demo_dir.rglob(target_file):
            test_files.append(img_file)
            found = True
            break
        if not found:
            print(f"Warning: {target_file} not found in demo directory")
    
    if not test_files:
        print("❌ No test files found. Please ensure test files exist in demo directory.")
        return

    print("="*80)
    print("GEMINI API COMPARISON TEST")
    print("="*80)
    print("This test demonstrates the cost implications of using advanced")
    print("commercial models compared to Dolphin's open-source approach.")
    print("="*80)
    
    # Initialize processor
    try:
        processor = GeminiDocumentProcessor(api_key)
    except ValueError as e:
        print(f"❌ {e}")
        return
    
    results_summary = {
        "test_type": "gemini_comparison",
        "timestamp": datetime.now().isoformat(),
        "pricing_info": processor.pricing,
        "tests": []
    }
    
    total_estimated_cost = 0.0
    
    # Process each test file
    for i, file_path in enumerate(test_files, 1):
        print(f"\n🔍 TEST {i}: Processing {file_path.name}")
        print(f"File: {file_path}")
        
        try:
            result = processor.process_document(file_path, output_dir)
            results_summary["tests"].append({
                "test_name": f"gemini_test_{i}",
                "file": str(file_path),
                "result": result
            })
            total_estimated_cost += result["estimated_cost_usd"]
            
        except Exception as e:
            print(f"❌ Error processing {file_path}: {str(e)}")
            results_summary["tests"].append({
                "test_name": f"gemini_test_{i}",
                "file": str(file_path),
                "error": str(e)
            })

    # Save overall summary
    results_summary["total_estimated_cost_usd"] = round(total_estimated_cost, 6)
    
    summary_file = output_dir / "gemini_test_summary.json"
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(results_summary, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Gemini tests completed!")
    print(f"💰 Total estimated cost: ${total_estimated_cost:.2f} USD")
    print(f"📊 Summary saved to: {summary_file}")
    print(f"📁 All results in: {output_dir}")
    
    print(f"\n💡 COST COMPARISON:")
    print(f"   - Gemini API cost for this test: ${total_estimated_cost:.6f} USD")
    print(f"   - Dolphin (open-source): $0.00 USD")
    print(f"   - Cost per document: ~${total_estimated_cost/max(1,len(test_files)):.6f} USD")
    print(f"   - Annual cost for 1000 docs: ~${total_estimated_cost*1000/max(1,len(test_files)):.2f} USD")


if __name__ == "__main__":
    main()
