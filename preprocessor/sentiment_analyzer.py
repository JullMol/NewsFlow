import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from tqdm import tqdm

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SENTIMENT_MODEL, SENTIMENT_LABELS, BATCH_SIZE, MAX_TOKEN_LENGTH

class SentimentAnalyzer:
    def __init__(self, model_name: str = SENTIMENT_MODEL):
        print(f"[SENTIMENT] Loading model: {model_name}")
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"  Using device: {self.device}")

        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self.model.to(self.device)
        self.model.eval()
        print(f"  Model loaded successfully!")

    def predict_single(self, text: str) -> dict:
        inputs = self.tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=MAX_TOKEN_LENGTH,
            padding=True,
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.model(**inputs)
            probs = torch.softmax(outputs.logits, dim=-1)
            predicted_class = torch.argmax(probs, dim=-1).item()
            confidence = probs[0][predicted_class].item()

        label_key = f"LABEL_{predicted_class}"
        return {
            "label": SENTIMENT_LABELS.get(label_key, "unknown"),
            "score": round(confidence, 4),
            "raw_label": label_key,
        }

    def predict_batch(self, texts: list[str], batch_size: int = BATCH_SIZE) -> list[dict]:
        results = []

        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i + batch_size]
            inputs = self.tokenizer(
                batch_texts,
                return_tensors="pt",
                truncation=True,
                max_length=MAX_TOKEN_LENGTH,
                padding=True,
            )
            inputs = {k: v.to(self.device) for k, v in inputs.items()}

            with torch.no_grad():
                outputs = self.model(**inputs)
                probs = torch.softmax(outputs.logits, dim=-1)
                predicted_classes = torch.argmax(probs, dim=-1)

            for j, pred_class in enumerate(predicted_classes):
                label_key = f"LABEL_{pred_class.item()}"
                results.append({
                    "label": SENTIMENT_LABELS.get(label_key, "unknown"),
                    "score": round(probs[j][pred_class].item(), 4),
                    "raw_label": label_key,
                })

        return results


def analyze_articles(articles: list[dict], analyzer: SentimentAnalyzer = None) -> list[dict]:
    if analyzer is None:
        analyzer = SentimentAnalyzer()

    texts = []
    for article in articles:
        title = article.get("title", "")
        content = article.get("content", "")[:500]
        combined = f"{title}. {content}" if title else content
        texts.append(combined)

    print(f"[SENTIMENT] Analyzing {len(texts)} articles")
    sentiments = analyzer.predict_batch(texts)

    for article, sentiment in zip(articles, sentiments):
        article["sentiment_label"] = sentiment["label"]
        article["sentiment_score"] = sentiment["score"]

    return articles


_analyzer_instance = None

def get_analyzer() -> SentimentAnalyzer:
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = SentimentAnalyzer()
    return _analyzer_instance


if __name__ == "__main__":
    analyzer = SentimentAnalyzer()

    test_texts = [
        "Presiden meresmikan jembatan baru yang megah di Kalimantan",
        "Korban banjir di Jakarta bertambah menjadi ratusan jiwa",
        "Pemerintah mengadakan rapat koordinasi rutin hari ini",
    ]

    for text in test_texts:
        result = analyzer.predict_single(text)
        print(f"Text: {text}")
        print(f"  Sentiment: {result['label']} (confidence: {result['score']})")
        print()