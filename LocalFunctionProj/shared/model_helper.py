import os
import logging
import time

_model = None
_model_loading = False
_model_load_error = None

def get_sentence_model():
    """
    Lazy-load the sentence transformer model with optimizations:
    - Only imports sentence-transformers when actually needed
    - Prevents multiple concurrent loading attempts
    - Caches load errors to fail fast on subsequent calls
    - Provides performance monitoring
    """
    global _model, _model_loading, _model_load_error
    
    # If we previously failed to load, fail fast
    if _model_load_error is not None:
        raise _model_load_error
    
    # If model is already loaded, return it
    if _model is not None:
        return _model
    
    # Prevent concurrent loading attempts
    if _model_loading:
        # Wait for other thread to finish loading
        import time
        max_wait = 30  # seconds
        wait_interval = 0.1
        waited = 0
        while _model_loading and waited < max_wait:
            time.sleep(wait_interval)
            waited += wait_interval
        
        if _model is not None:
            return _model
        elif _model_load_error is not None:
            raise _model_load_error
        else:
            raise RuntimeError("Model loading timed out")
    
    # Begin loading
    _model_loading = True
    start_time = time.time()
    
    try:
        # Check if model loading should be skipped (for testing)
        if os.getenv("SKIP_ML_MODELS", "").lower() == "true":
            raise RuntimeError("ML model loading disabled via SKIP_ML_MODELS environment variable")
        
        # Import only when needed to reduce startup time
        logging.info("Starting lazy import of sentence-transformers...")
        from sentence_transformers import SentenceTransformer
        
        model_name = os.getenv("SENTENCE_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        logging.info(f"Loading sentence transformer model: {model_name}")
        
        _model = SentenceTransformer(model_name)
        load_time = time.time() - start_time
        logging.info(f"Sentence transformer model loaded successfully in {load_time:.2f} seconds")
        
        return _model
        
    except ImportError as e:
        _model_load_error = ImportError(f"Failed to import sentence-transformers. Please ensure it's installed: {e}")
        logging.error(f"Import error: {_model_load_error}")
        raise _model_load_error
    except Exception as e:
        _model_load_error = Exception(f"Failed to load sentence transformer model: {e}")
        logging.error(f"Model loading error: {_model_load_error}")
        raise _model_load_error
    finally:
        _model_loading = False

def clear_model_cache():
    """Clear the cached model (useful for testing or memory management)"""
    global _model, _model_load_error
    _model = None
    _model_load_error = None
    logging.info("Model cache cleared")

def is_model_loaded():
    """Check if model is currently loaded without triggering a load"""
    return _model is not None 