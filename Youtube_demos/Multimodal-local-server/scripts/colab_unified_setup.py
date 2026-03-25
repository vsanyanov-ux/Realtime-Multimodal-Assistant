# ==========================================
# UNIFIED GOOGLE COLAB SETUP SCRIPT
# ==========================================
# 1. Open https://colab.research.google.com/
# 2. Add a new code cell.
# 3. Change Runtime Type to "T4 GPU" (Runtime -> Change runtime type).
# 4. Paste ALL of this code and run it.

import os
import subprocess
import time
import sys

# --- STEP 1: INSTALL DEPENDENCIES ---
print("--- [1/3] Installing system and python dependencies (3-5 mins) ---")
# Use -q for quiet install
os.system("pip install -q transformers torch torchvision torchaudio websockets Pillow numpy kokoro spacy qwen-vl-utils accelerate bitsandbytes")
os.system("python -m spacy download en_core_web_sm -q")
os.system("npm install -g localtunnel -q")

# --- STEP 2: CREATE THE BACKEND SCRIPT ---
print("--- [2/3] Writing main.py ---")
main_py_content = r'''
import asyncio
import json
import websockets
import base64
import torch
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline, Qwen2_5_VLForConditionalGeneration, BitsAndBytesConfig
import numpy as np
import logging
import sys
import io
from PIL import Image
import time
import os
from datetime import datetime
from kokoro import KPipeline

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class AudioSegmentDetector:
    def __init__(self, sample_rate=16000, energy_threshold=0.005, silence_duration=0.8, min_speech_duration=0.8, max_speech_duration=15):
        self.sample_rate = sample_rate
        self.energy_threshold = energy_threshold
        self.silence_samples = int(silence_duration * sample_rate)
        self.min_speech_samples = int(min_speech_duration * sample_rate)
        self.max_speech_samples = int(max_speech_duration * sample_rate)
        self.audio_buffer = bytearray()
        self.is_speech_active = False
        self.silence_counter = 0
        self.speech_start_idx = 0
        self.lock = asyncio.Lock()
        self.segment_queue = asyncio.Queue()
        self.segments_detected = 0
        self.tts_playing = False
        self.tts_lock = asyncio.Lock()
    
    async def set_tts_playing(self, is_playing):
        async with self.tts_lock:
            self.tts_playing = is_playing
    
    async def add_audio(self, audio_bytes):
        async with self.lock:
            async with self.tts_lock:
                if self.tts_playing: return None
            self.audio_buffer.extend(audio_bytes)
            audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            if len(audio_array) > 0:
                energy = np.sqrt(np.mean(audio_array**2))
                if not self.is_speech_active and energy > self.energy_threshold:
                    self.is_speech_active = True
                    self.speech_start_idx = max(0, len(self.audio_buffer) - len(audio_bytes))
                    self.silence_counter = 0
                    logger.info(f"Speech start detected (energy: {energy:.6f})")
                elif self.is_speech_active:
                    if energy > self.energy_threshold: self.silence_counter = 0
                    else:
                        self.silence_counter += len(audio_array)
                        if self.silence_counter >= self.silence_samples:
                            speech_end_idx = len(self.audio_buffer) - self.silence_counter
                            speech_segment = bytes(self.audio_buffer[self.speech_start_idx:speech_end_idx])
                            self.is_speech_active = False
                            self.silence_counter = 0
                            self.audio_buffer = self.audio_buffer[speech_end_idx:]
                            if len(speech_segment) >= self.min_speech_samples * 2:
                                self.segments_detected += 1
                                logger.info(f"Speech segment detected: {len(speech_segment)/2/self.sample_rate:.2f}s")
                                await self.segment_queue.put(speech_segment)
                                return speech_segment
                        elif (len(self.audio_buffer) - self.speech_start_idx) > self.max_speech_samples * 2:
                            speech_segment = bytes(self.audio_buffer[self.speech_start_idx:self.speech_start_idx + self.max_speech_samples * 2])
                            self.speech_start_idx += self.max_speech_samples * 2
                            self.segments_detected += 1
                            logger.info(f"Max duration speech segment: {len(speech_segment)/2/self.sample_rate:.2f}s")
                            await self.segment_queue.put(speech_segment)
                            return speech_segment
            return None

    async def get_next_segment(self):
        try: return await asyncio.wait_for(self.segment_queue.get(), timeout=0.1)
        except asyncio.TimeoutError: return None

class WhisperTranscriber:
    _instance = None
    @classmethod
    def get_instance(cls):
        if cls._instance is None: cls._instance = cls()
        return cls._instance
    def __init__(self):
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self.torch_dtype = torch.float16 if self.device != "cpu" else torch.float32
        model_id = "openai/whisper-small"
        self.model = AutoModelForSpeechSeq2Seq.from_pretrained(model_id, torch_dtype=self.torch_dtype, low_cpu_mem_usage=True, use_safetensors=True).to(self.device)
        self.processor = AutoProcessor.from_pretrained(model_id)
        self.pipe = pipeline("automatic-speech-recognition", model=self.model, tokenizer=self.processor.tokenizer, feature_extractor=self.processor.feature_extractor, torch_dtype=self.torch_dtype, device=self.device)
        logger.info("Whisper model ready")
    async def transcribe(self, audio_bytes, sample_rate=16000):
        try:
            audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            if len(audio_array) < 1000: return ""
            result = await asyncio.get_event_loop().run_in_executor(None, lambda: self.pipe({"array": audio_array, "sampling_rate": sample_rate}, generate_kwargs={"task": "transcribe", "language": "english", "temperature": 0.0}))
            text = result.get("text", "").strip()
            logger.info(f"Transcription: '{text}'")
            return text
        except Exception as e:
            logger.error(f"Transcribe error: {e}"); return ""

class QwenMultimodalProcessor:
    _instance = None
    @classmethod
    def get_instance(cls):
        if cls._instance is None: cls._instance = cls()
        return cls._instance
    def __init__(self):
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        model_id = "Qwen/Qwen2.5-VL-3B-Instruct"
        if torch.cuda.is_available():
            q_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True)
            self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(model_id, quantization_config=q_config, device_map="auto")
        else:
            self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(model_id, torch_dtype=torch.bfloat16, device_map="cpu")
        self.processor = AutoProcessor.from_pretrained(model_id)
        self.last_image = None
        self.lock = asyncio.Lock()
        logger.info("Qwen ready (GPU Enabled)")
    async def set_image(self, image_data):
        async with self.lock:
            try:
                img = Image.open(io.BytesIO(image_data))
                new_size = (int(img.size[0] * 0.75), int(img.size[1] * 0.75))
                self.last_image = img.resize(new_size, Image.Resampling.LANCZOS)
                return True
            except Exception as e: logger.error(f"Image error: {e}"); return False
    async def generate(self, text):
        async with self.lock:
            try:
                if not self.last_image: return f"No image: {text}"
                messages = [{"role": "system", "content": "You are a helpful assistant talking about images. Be concise (2-3 sentences), fluent and conversational."},
                            {"role": "user", "content": [{"type": "image", "image": self.last_image}, {"type": "text", "text": text}]}]
                text_input = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                inputs = self.processor(text=[text_input], images=[self.last_image], padding=True, return_tensors="pt").to(self.device)
                gen_ids = self.model.generate(**inputs, max_new_tokens=128, do_sample=True, temperature=0.7, top_p=0.9, repetition_penalty=1.2)
                out_ids = [o[len(i):] for i, o in zip(inputs.input_ids, gen_ids)]
                output = self.processor.batch_decode(out_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]
                logger.info(f"Qwen response: {output[:50]}...")
                return output
            except Exception as e: logger.error(f"Gen error: {e}"); return f"Error: {text}"

class KokoroTTSProcessor:
    _instance = None
    @classmethod
    def get_instance(cls):
        if cls._instance is None: cls._instance = cls()
        return cls._instance
    def __init__(self):
        try:
            self.pipeline = KPipeline(lang_code='a')
            self.default_voice = 'af_sarah'
            logger.info("Kokoro ready")
        except Exception as e: logger.error(f"TTS init error: {e}"); self.pipeline = None
    async def synthesize_speech(self, text):
        if not text or not self.pipeline: return None
        try:
            audio_segments = []
            generator = await asyncio.get_event_loop().run_in_executor(None, lambda: self.pipeline(text, voice=self.default_voice, speed=1, split_pattern=r'[.!?。！？]+'))
            for _, _, audio in generator: audio_segments.append(audio)
            if audio_segments: return np.concatenate(audio_segments)
            return None
        except Exception as e: logger.error(f"TTS error: {e}"); return None

async def handle_client(websocket):
    try:
        await websocket.recv(); logger.info("Client connected")
        detector = AudioSegmentDetector()
        transcriber = WhisperTranscriber.get_instance()
        qwen = QwenMultimodalProcessor.get_instance()
        tts = KokoroTTSProcessor.get_instance()
        
        async def send_keepalive():
            while True:
                try: await websocket.ping(); await asyncio.sleep(10)
                except: break
        
        async def detect_speech():
            while True:
                try:
                    seg = await detector.get_next_segment()
                    if seg:
                        tx = await transcriber.transcribe(seg)
                        if tx:
                            await websocket.send(json.dumps({"transcription": {"text": tx, "sender": "User", "finished": True}}))
                            resp = await qwen.generate(tx)
                            await websocket.send(json.dumps({"text": resp}))
                            await detector.set_tts_playing(True)
                            try:
                                aud = await tts.synthesize_speech(resp)
                                if aud is not None:
                                    b64 = base64.b64encode((aud * 32767).astype(np.int16).tobytes()).decode('utf-8')
                                    await websocket.send(json.dumps({"audio": b64}))
                                    dur = len(aud)/24000; intervals = int(dur/0.5)
                                    for _ in range(intervals): await websocket.ping(); await asyncio.sleep(0.5)
                                    rem = dur - (intervals*0.5)
                                    if rem > 0: await websocket.ping(); await asyncio.sleep(rem)
                            except: break
                            finally: await detector.set_tts_playing(False)
                    await asyncio.sleep(0.01)
                except: break
        
        async def receive_data():
            async for msg in websocket:
                try:
                    data = json.loads(msg)
                    if "realtime_input" in data:
                        for chunk in data["realtime_input"]["media_chunks"]:
                            if chunk["mime_type"] == "audio/pcm": await detector.add_audio(base64.b64decode(chunk["data"]))
                            elif chunk["mime_type"] == "image/jpeg" and not detector.tts_playing: await qwen.set_image(base64.b64decode(chunk["data"]))
                    if "image" in data and not detector.tts_playing: await qwen.set_image(base64.b64decode(data["image"]))
                except Exception as e: logger.error(f"Recv error: {e}")

        await asyncio.gather(receive_data(), detect_speech(), send_keepalive(), return_exceptions=True)
    except: logger.info("Session ended")

async def main():
    try:
        WhisperTranscriber.get_instance(); QwenMultimodalProcessor.get_instance(); KokoroTTSProcessor.get_instance()
        async with websockets.serve(handle_client, "0.0.0.0", 9073, ping_interval=20, ping_timeout=60):
            logger.info("Server running on 0.0.0.0:9073")
            await asyncio.Future()
    except Exception as e: logger.error(f"Server error: {e}")

if __name__ == "__main__": asyncio.run(main())
'''

with open("main.py", "w") as f:
    f.write(main_py_content)

# --- STEP 3: START TUNNEL AND SERVER ---
print("--- [3/3] Starting Tunnel and Server ---")
import threading

def run_tunnel():
    # Execute localtunnel and capture its output to display the URL
    # Using bufsize=1 and universal_newlines=True to get strings directly
    p = subprocess.Popen(['lt', '--port', '9073'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    for line in p.stdout:
        print(line.strip())

# Start tunnel in a separate thread
threading.Thread(target=run_tunnel, daemon=True).start()

print("\n" + "="*50)
print("INSTRUCTIONS:")
print("1. Wait for Colab to finish downloading models (~5-10 mins).")
print("2. Look at the output BELOW for 'your url is: https://xxxx.loca.lt'")
print("3. IMPORTANT: Go to that link in browser and click 'Click to Continue' to bypass localtunnel screen.")
print("4. Copy that URL (change https:// to wss://) and tell it to me, or update App.tsx.")
print("="*50 + "\n")

# Start the actual python server
os.system("python main.py")
