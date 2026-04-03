"""
WorkMind NLP Engine
CONFIDENTIAL - PRIVATE REPOSITORY - NOT FOR PUBLIC DISTRIBUTION

Moduli di intelligenza artificiale:
- Classifier: classifica documenti (fattura, ordine, contratto, ...)
- Extractor: estrae entità (nomi, date, importi, codici)
- Summarizer: genera riassunti di documenti
- TaskDecomposer: identifica processi impliciti
- PatternDetector: trova pattern temporali e colli di bottiglia
- HallucinationGuard: valida output AI prima di presentarli
"""

from nlp.classifier import DocumentClassifier
from nlp.extractor import EntityExtractor
from nlp.summarizer import DocumentSummarizer
from nlp.task_decomposer import TaskDecomposer
from nlp.pattern_detector import PatternDetector
from nlp.hallucination_guard import HallucinationGuard

__all__ = [
    "DocumentClassifier",
    "EntityExtractor",
    "DocumentSummarizer",
    "TaskDecomposer",
    "PatternDetector",
    "HallucinationGuard",
]
