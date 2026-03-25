"""
Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
SPDX-License-Identifier: MIT
"""

import argparse
import glob
import os

import cv2
import torch
from PIL import Image
from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration
from qwen_vl_utils import process_vision_info

from utils.utils import *


class DOLPHIN:
    def __init__(self, model_id_or_path, quantization=None):
        """Initialize the Hugging Face model
        
        Args:
            model_id_or_path: Path to local model or Hugging Face model ID
            quantization: Quantization mode - None, '8bit', or '4bit' (default: None)
        """
        # Load model from local path or Hugging Face hub
        self.processor = AutoProcessor.from_pretrained(model_id_or_path)
        
        # Configure quantization settings
        if quantization == '8bit':
            # 8-bit quantization: ~50% memory reduction, minimal accuracy loss
            self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                model_id_or_path,
                device_map="auto",
                load_in_8bit=True,  # Reduces memory usage by ~50%
            )
        elif quantization == '4bit':
            # 4-bit quantization: ~75% memory reduction, slight accuracy loss
            self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                model_id_or_path,
                device_map="auto",
                load_in_4bit=True,  # Reduces memory usage by ~75%
            )
        else:
            # No quantization: Full precision (bfloat16)
            self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                model_id_or_path,
                device_map="auto",
                torch_dtype=torch.bfloat16,
            )
        
        self.model.eval()
        
        # Device is automatically set by device_map
        self.device = self.model.device
        
        # set tokenizer
        self.tokenizer = self.processor.tokenizer
        self.tokenizer.padding_side = "left"

    def chat(self, prompt, image):
        # Check if we're dealing with a batch
        is_batch = isinstance(image, list)
        
        if not is_batch:
            # Single image, wrap it in a list for consistent processing
            images = [image]
            prompts = [prompt]
        else:
            # Batch of images
            images = image
            prompts = prompt if isinstance(prompt, list) else [prompt] * len(images)
        
        assert len(images) == len(prompts)
        
        # preprocess all images
        processed_images = [resize_img(img) for img in images]
        # generate all messages
        all_messages = []
        for img, question in zip(processed_images, prompts):
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "image": img,
                        },
                        {"type": "text", "text": question}
                    ],
                }
            ]
            all_messages.append(messages)
        # prepare all texts
        texts = [
            self.processor.apply_chat_template(
                msgs, tokenize=False, add_generation_prompt=True
            )
            for msgs in all_messages
        ]
        # collect all image inputs
        all_image_inputs = []
        all_video_inputs = None
        for msgs in all_messages:
            image_inputs, video_inputs = process_vision_info(msgs)
            all_image_inputs.extend(image_inputs)
        # prepare model inputs
        inputs = self.processor(
            text=texts,
            images=all_image_inputs if all_image_inputs else None,
            videos=all_video_inputs if all_video_inputs else None,
            padding=True,
            return_tensors="pt",
        )
        inputs = inputs.to(self.model.device)
        # inference
        generated_ids = self.model.generate(
            **inputs,
            max_new_tokens=4096,
            do_sample=False,
            temperature=None,
            # repetition_penalty=1.05
        )
        generated_ids_trimmed = [
            out_ids[len(in_ids):] 
            for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]
        
        results = self.processor.batch_decode(
            generated_ids_trimmed, 
            skip_special_tokens=True, 
            clean_up_tokenization_spaces=False
        )
        # Return a single result for single image input
        if not is_batch:
            return results[0]
        return results


def process_element(input_path, model, element_type, save_dir=None):
    """Process element(s) from image or PDF file
    
    Args:
        input_path: Path to the input image or PDF file
        model: DOLPHIN model instance
        element_type: Type of element ('text', 'table', 'formula', 'code')
        save_dir: Directory to save results (default: same as input directory)
        
    Returns:
        Tuple of (parsed_content, recognition_results) for single image, 
        or List of results for PDF pages
        
    Raises:
        FileNotFoundError: If input file doesn't exist
        Exception: If file processing fails
    """
    file_ext = os.path.splitext(input_path)[1].lower()
    
    if file_ext == '.pdf':
        # Handle PDF files
        return process_pdf_elements(input_path, model, element_type, save_dir)
    else:
        # Handle regular image files
        return process_single_element_image(input_path, model, element_type, save_dir)


def process_pdf_elements(pdf_path, model, element_type, save_dir):
    """Process elements from all pages of a PDF
    
    Args:
        pdf_path: Path to the PDF file
        model: DOLPHIN model instance
        element_type: Type of element to process
        save_dir: Directory to save results
        
    Returns:
        List of results from all pages
    """
    # Convert PDF to images
    images = convert_pdf_to_images(pdf_path)
    if not images:
        raise Exception(f"Failed to convert PDF {pdf_path} to images")
    
    all_results = []
    
    # Process each page
    for page_idx, pil_image in enumerate(images):
        print(f"Processing page {page_idx + 1}/{len(images)}")
        
        # Generate output name for this page
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        page_name = f"{base_name}_page_{page_idx + 1:03d}"
        
        try:
            result, recognition_results = process_single_element_from_image(
                pil_image, model, element_type, save_dir, page_name
            )
            
            # Add page information
            page_result = {
                "page_number": page_idx + 1,
                "content": result,
                "recognition_results": recognition_results
            }
            all_results.append(page_result)
            
        except Exception as e:
            print(f"Error processing page {page_idx + 1}: {str(e)}")
            continue
    
    return all_results


def process_single_element_image(image_path, model, element_type, save_dir):
    """Process a single element image file
    
    Args:
        image_path: Path to the element image
        model: DOLPHIN model instance
        element_type: Type of element ('text', 'table', 'formula', 'code')
        save_dir: Directory to save results (default: same as input directory)
        
    Returns:
        Tuple of (parsed_content, recognition_results)
    """
    # Load and prepare image
    try:
        pil_image = Image.open(image_path).convert("RGB")
        image_name = os.path.splitext(os.path.basename(image_path))[0]
        return process_single_element_from_image(pil_image, model, element_type, save_dir, image_name)
    except Exception as e:
        raise FileNotFoundError(f"Failed to load image {image_path}: {str(e)}")


def process_single_element_from_image(pil_image, model, element_type, save_dir, image_name):
    """Process element from a PIL Image object
    
    Args:
        pil_image: PIL Image object
        model: DOLPHIN model instance
        element_type: Type of element ('text', 'table', 'formula', 'code')
        save_dir: Directory to save results
        image_name: Name for output files
        
    Returns:
        Tuple of (parsed_content, recognition_results)
    """
    # Select appropriate prompt based on element type
    if element_type == "table":
        prompt = "Parse the table in the image."
        label = "tab"
    elif element_type == "formula":
        prompt = "Read formula in the image."
        label = "equ"
    elif element_type == "code":
        prompt = "Read code in the image."
        label = "code"
    else:  # Default to text
        prompt = "Read text in the image."
        label = "para"
    
    # Process the element
    try:
        result = model.chat(prompt, pil_image)
        
        # Create recognition result in the same format as the document parser
        recognition_results = [
            {
                "label": label,
                "text": result.strip(),
            }
        ]
        
        # Save results if save_dir is provided
        if save_dir:
            save_outputs(recognition_results, pil_image, image_name, save_dir)
            print(f"Results saved to {save_dir}")
            
    except Exception as e:
        print(f"Error processing element: {str(e)}")
        raise
    
    return result, recognition_results


def main():
    parser = argparse.ArgumentParser(description="Element-level processing using DOLPHIN model")
    parser.add_argument("--model_path", default="./hf_model", help="Path to Hugging Face model")
    parser.add_argument("--input_path", type=str, required=True, help="Path to input image/PDF or directory of files")
    parser.add_argument(
        "--element_type",
        type=str,
        choices=["text", "table", "formula", "code"],
        default="text",
        help="Type of element to process (text, table, formula)",
    )
    parser.add_argument(
        "--save_dir",
        type=str,
        default=None,
        help="Directory to save parsing results (default: same as input directory)",
    )
    parser.add_argument("--print_results", action="store_true", help="Print recognition results to console")
    parser.add_argument(
        "--quantization",
        type=str,
        choices=[None, "8bit", "4bit"],
        default=None,
        help="Quantization mode to reduce GPU memory: '8bit' (~50%% reduction) or '4bit' (~75%% reduction)",
    )
    args = parser.parse_args()
    
    # Load Model
    model = DOLPHIN(args.model_path, quantization=args.quantization)
    
    # Set save directory
    save_dir = args.save_dir or (
        args.input_path if os.path.isdir(args.input_path) else os.path.dirname(args.input_path)
    )
    setup_output_dirs(save_dir)
    
    # Collect files (images and PDFs)
    if os.path.isdir(args.input_path):
        # Support both image and PDF files
        file_extensions = [".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG", ".pdf", ".PDF"]
        
        input_files = []
        for ext in file_extensions:
            input_files.extend(glob.glob(os.path.join(args.input_path, f"*{ext}")))
        input_files = sorted(input_files)
    else:
        if not os.path.exists(args.input_path):
            raise FileNotFoundError(f"Input path {args.input_path} does not exist")
        
        # Check if it's a supported file type
        file_ext = os.path.splitext(args.input_path)[1].lower()
        supported_exts = ['.jpg', '.jpeg', '.png', '.pdf']
        
        if file_ext not in supported_exts:
            raise ValueError(f"Unsupported file type: {file_ext}. Supported types: {supported_exts}")
        
        input_files = [args.input_path]
    
    total_samples = len(input_files)
    print(f"\nTotal files to process: {total_samples}")
    
    # Process files one by one
    for file_path in input_files:
        print(f"\nProcessing {file_path}")
        try:
            result = process_element(
                input_path=file_path,
                model=model,
                element_type=args.element_type,
                save_dir=save_dir,
            )

            if args.print_results:
                print("\nRecognition result:")
                file_ext = os.path.splitext(file_path)[1].lower()
                if file_ext == '.pdf':
                    # For PDF, result is a list of page results
                    for page_result in result:
                        print(f"Page {page_result['page_number']}: {page_result['content']}")
                else:
                    # For images, result is a tuple (content, recognition_results)
                    print(result[0])
                print("-" * 40)
                
            print(f"✓ Processing completed for {file_path}")
            
        except Exception as e:
            print(f"✗ Error processing {file_path}: {str(e)}")
            continue


if __name__ == "__main__":
    main()
