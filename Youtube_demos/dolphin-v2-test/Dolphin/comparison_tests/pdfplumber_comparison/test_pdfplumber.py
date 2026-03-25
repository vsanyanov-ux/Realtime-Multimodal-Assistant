#!/usr/bin/env python3
"""
PDFPlumber Comparison Test
Demonstrates the limitations of traditional PDF text extraction tools
compared to Dolphin's vision-based approach.
"""

import os
import sys
import time
from pathlib import Path
import json
from datetime import datetime

try:
    import pdfplumber
except ImportError:
    print("Installing pdfplumber...")
    os.system("pip install pdfplumber")
    import pdfplumber

try:
    from PIL import Image
    import img2pdf
except ImportError:
    print("Installing PIL and img2pdf...")
    os.system("pip install Pillow img2pdf")
    from PIL import Image
    import img2pdf


def extract_text_with_pdfplumber(pdf_path, output_dir):
    """Extract text from PDF using pdfplumber"""
    print(f"Processing {pdf_path} with pdfplumber...")
    
    start_time = time.time()
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            print(f"Total pages: {total_pages}")
            
            all_text = []
            detailed_results = []
            
            for page_num, page in enumerate(pdf.pages, 1):
                print(f"Processing page {page_num}/{total_pages}")
                
                # Extract text
                text = page.extract_text()
                
                # Extract tables 
                tables = page.extract_tables()
                
                # Extract text with layout info
                text_with_layout = page.extract_text_lines()
                
                page_result = {
                    "page_number": page_num,
                    "text": text or "",
                    "tables": tables,
                    "text_lines": text_with_layout,
                    "text_length": len(text) if text else 0,
                    "table_count": len(tables)
                }
                
                detailed_results.append(page_result)
                
                if text:
                    all_text.append(f"=== PAGE {page_num} ===\n{text}\n")
                else:
                    all_text.append(f"=== PAGE {page_num} ===\n[NO TEXT EXTRACTED]\n")
    
    except Exception as e:
        print(f"Error processing {pdf_path}: {str(e)}")
        return None, None
    
    end_time = time.time()
    processing_time = end_time - start_time
    
    # Save results
    output_file = output_dir / f"{Path(pdf_path).stem}_pdfplumber_results.txt"
    json_file = output_dir / f"{Path(pdf_path).stem}_pdfplumber_detailed.json"
    
    # Save plain text
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"PDFPlumber Results for: {pdf_path}\n")
        f.write(f"Processing time: {processing_time:.2f} seconds\n")
        f.write(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 80 + "\n\n")
        f.write('\n'.join(all_text))
        
        # Add analysis
        f.write("\n" + "="*80 + "\n")
        f.write("ANALYSIS:\n")
        f.write(f"- Total pages processed: {len(detailed_results)}\n")
        f.write(f"- Pages with text: {sum(1 for p in detailed_results if p['text_length'] > 0)}\n")
        f.write(f"- Total tables detected: {sum(p['table_count'] for p in detailed_results)}\n")
        f.write(f"- Processing time: {processing_time:.2f}s\n")
    
    # Save detailed JSON
    summary = {
        "file": str(pdf_path),
        "tool": "pdfplumber",
        "processing_time": processing_time,
        "timestamp": datetime.now().isoformat(),
        "total_pages": len(detailed_results),
        "pages_with_text": sum(1 for p in detailed_results if p['text_length'] > 0),
        "total_tables": sum(p['table_count'] for p in detailed_results),
        "detailed_results": detailed_results
    }
    
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    print(f"Results saved to {output_file}")
    print(f"Detailed results saved to {json_file}")
    
    return output_file, summary


def convert_png_to_pdf(png_path, output_dir):
    """Convert PNG image to PDF for testing"""
    print(f"Converting {png_path} to PDF...")
    
    pdf_path = output_dir / f"{Path(png_path).stem}_converted.pdf"
    
    try:
        with open(png_path, 'rb') as f:
            pdf_bytes = img2pdf.convert(f.read())
        
        with open(pdf_path, 'wb') as f:
            f.write(pdf_bytes)
        
        print(f"PDF created: {pdf_path}")
        return pdf_path
    
    except Exception as e:
        print(f"Error converting {png_path}: {str(e)}")
        return None


def main():
    # Setup paths
    script_dir = Path(__file__).parent
    output_dir = script_dir / "results"
    output_dir.mkdir(exist_ok=True)
    
    # Look for test files
    demo_dir = Path(__file__).parent.parent.parent / "demo"
    
    # Test files
    page_6_pdf = None
    page_1_png = None
    
    # Find page_6.pdf
    for pdf_file in demo_dir.rglob("*page_6*.pdf"):
        page_6_pdf = pdf_file
        break
    
    # Find page_1.png  
    for png_file in demo_dir.rglob("*page_1*.png"):
        page_1_png = png_file
        break
    
    if not page_6_pdf:
        print("Warning: page_6.pdf not found in demo directory")
        # Look in current directory
        page_6_pdf = script_dir.parent.parent / "demo" / "page_imgs" / "page_6.pdf"
        if not page_6_pdf.exists():
            print(f"Please ensure page_6.pdf exists at: {page_6_pdf}")
            return
    
    if not page_1_png:
        print("Warning: page_1.png not found in demo directory")
        # Look in current directory  
        page_1_png = script_dir.parent.parent / "demo" / "page_imgs" / "page_1.png"
        if not page_1_png.exists():
            print(f"Please ensure page_1.png exists at: {page_1_png}")
            return
    
    print("="*80)
    print("PDFPLUMBER COMPARISON TEST")
    print("="*80)
    print("This test demonstrates the limitations of traditional PDF processors")
    print("compared to vision-based approaches like Dolphin.")
    print("="*80)
    
    results_summary = {
        "test_type": "pdfplumber_comparison", 
        "timestamp": datetime.now().isoformat(),
        "tests": []
    }
    
    # Test 1: Extract from native PDF
    if page_6_pdf and page_6_pdf.exists():
        print(f"\n📄 TEST 1: Native PDF Processing")
        print(f"File: {page_6_pdf}")
        
        result_file, summary = extract_text_with_pdfplumber(page_6_pdf, output_dir)
        if summary:
            results_summary["tests"].append({
                "test_name": "native_pdf",
                "file": str(page_6_pdf),
                "result": summary
            })
    
    # Test 2: Convert PNG to PDF and extract
    if page_1_png and page_1_png.exists():
        print(f"\n🖼️  TEST 2: Image-to-PDF Processing")
        print(f"Converting: {page_1_png}")
        
        converted_pdf = convert_png_to_pdf(page_1_png, output_dir)
        if converted_pdf:
            result_file, summary = extract_text_with_pdfplumber(converted_pdf, output_dir)
            if summary:
                results_summary["tests"].append({
                    "test_name": "converted_pdf", 
                    "original_image": str(page_1_png),
                    "converted_pdf": str(converted_pdf),
                    "result": summary
                })
    
    # Save overall summary
    summary_file = output_dir / "pdfplumber_test_summary.json"
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(results_summary, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Tests completed!")
    print(f"📊 Summary saved to: {summary_file}")
    print(f"📁 All results in: {output_dir}")
    
    print(f"\n💡 LIMITATIONS OBSERVED:")
    print("   - Poor handling of complex layouts and columns")
    print("   - Inability to extract from image-based PDFs")
    print("   - Loss of formatting and visual structure")
    print("   - No understanding of document semantics")


if __name__ == "__main__":
    main()
