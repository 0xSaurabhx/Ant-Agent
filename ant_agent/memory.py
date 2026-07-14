import os
import json
import math
from pathlib import Path
from datetime import datetime

from ant_agent.config import MEMORY_PATH

class SimpleVectorDB:
    def __init__(self, config, memory_file=None):
        self.config = config
        self.memory_file = Path(memory_file) if memory_file else MEMORY_PATH
        # Ensure parent directory exists
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)
        self.load()

    def load(self):
        if self.memory_file.exists():
            try:
                with open(self.memory_file, "r") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = []
        else:
            self.data = []

    def save(self):
        try:
            with open(self.memory_file, "w") as f:
                json.dump(self.data, f, indent=4)
        except Exception as e:
            print(f"Error saving memory: {e}")

    def get_embedding(self, text: str):
        provider = self.config.get("embedding_provider", "mock")
        if provider == "openai":
            try:
                import openai
                client = openai.OpenAI(
                    base_url=self.config.get("embedding_base_url", "https://api.openai.com/v1"),
                    api_key=self.config.get("llm_api_key", "dummy")
                )
                response = client.embeddings.create(
                    model=self.config.get("embedding_model", "text-embedding-3-small"),
                    input=text
                )
                return response.data[0].embedding
            except Exception as e:
                print(f"OpenAI embedding error: {e}")
        elif provider == "ollama":
            import httpx
            # Call Ollama API
            url = f"{self.config.get('embedding_base_url', 'http://localhost:11434/v1')}/embeddings"
            headers = {"Content-Type": "application/json"}
            payload = {
                "model": self.config.get("embedding_model", "nomic-embed-text"),
                "input": text
            }
            try:
                response = httpx.post(url, json=payload, timeout=10.0)
                if response.status_code == 200:
                    return response.json()["data"][0]["embedding"]
            except Exception as e:
                print(f"Ollama embedding error: {e}")
        
        # Fallback / Mock provider: Use simple TF-IDF-like bag of words matching
        return self._get_tfidf_vector(text)

    def _get_tfidf_vector(self, text: str):
        # We represent text as a frequency map of normalized words
        words = [w.strip(".,!?\"'()[]{}").lower() for w in text.split()]
        words = [w for w in words if len(w) > 2]
        freq = {}
        for w in words:
            freq[w] = freq.get(w, 0) + 1
        return freq

    def store(self, text: str):
        vector = self.get_embedding(text)
        record = {
            "text": text,
            "vector": vector,
            "timestamp": datetime.now().isoformat()
        }
        self.data.append(record)
        self.save()
        return True

    def recall(self, query: str, limit: int = 5):
        if not self.data:
            return []
        
        query_vector = self.get_embedding(query)
        results = []
        
        for item in self.data:
            item_vector = item.get("vector")
            
            # If both are lists, compute cosine similarity
            if isinstance(query_vector, list) and isinstance(item_vector, list) and len(query_vector) == len(item_vector):
                score = self._cosine_similarity(query_vector, item_vector)
            else:
                # Fallback: compute bag of words similarity
                q_tfidf = query_vector if isinstance(query_vector, dict) else self._get_tfidf_vector(query)
                i_tfidf = item_vector if isinstance(item_vector, dict) else self._get_tfidf_vector(item.get("text", ""))
                score = self._bag_of_words_similarity(q_tfidf, i_tfidf)
                
            results.append((score, item["text"], item["timestamp"]))

        # Sort by score descending
        results.sort(key=lambda x: x[0], reverse=True)
        return [{"text": text, "timestamp": ts, "score": score} for score, text, ts in results[:limit]]

    def _cosine_similarity(self, v1, v2):
        dot_product = sum(a * b for a, b in zip(v1, v2))
        magnitude_v1 = math.sqrt(sum(a * a for a in v1))
        magnitude_v2 = math.sqrt(sum(b * b for b in v2))
        if magnitude_v1 == 0 or magnitude_v2 == 0:
            return 0.0
        return dot_product / (magnitude_v1 * magnitude_v2)

    def _bag_of_words_similarity(self, v1: dict, v2: dict):
        # Calculate cosine similarity on term frequency dictionaries
        intersection = set(v1.keys()) & set(v2.keys())
        numerator = sum(v1[x] * v2[x] for x in intersection)
        
        sum1 = sum(v1[x] ** 2 for x in v1.keys())
        sum2 = sum(v2[x] ** 2 for x in v2.keys())
        denominator = math.sqrt(sum1) * math.sqrt(sum2)
        
        if not denominator:
            return 0.0
        return float(numerator) / denominator
