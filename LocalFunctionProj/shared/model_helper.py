from sentence_transformers import SentenceTransformer
import os

_model = None

def get_sentence_model():
    global _model
    if _model is None:
        _model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    return _model 