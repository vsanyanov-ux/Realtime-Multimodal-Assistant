# Google Colab Setup for Multimodal Backend
# 1. Open Google Colab: https://colab.research.google.com/
# 2. Change runtime type to "T4 GPU" (Runtime -> Change runtime type).
# 3. Paste and run this code in a cell.

import os

# Install dependencies (this takes ~2-3 mins)
print("Installing dependencies...")
os.system("pip install -q transformers torch torchvision torchaudio websockets Pillow numpy kokoro spacy qwen-vl-utils")
os.system("python -m spacy download en_core_web_sm")
os.system("npm install -g localtunnel")

# Write the main.py file to Colab
with open("main.py", "w") as f:
    f.write('''
# Paste the content of your local main.py here OR
# I will generate the full unified code below
''')

# Since I (the AI) have the code, I will provide the FULL script below 
# for the user to copy-paste into ONE cell.
