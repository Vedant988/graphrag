import re

QUESTION_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "how", "in", "into", "is", "it", "of", "on", "or", "that", "the",
    "their", "them", "these", "they", "this", "those", "to", "was",
    "were", "what", "when", "where", "which", "who", "with",
}


def extract_question_keywords(question):
    return {
        token
        for token in re.findall(r"[a-z0-9_]+", question.lower())
        if len(token) > 2 and token not in QUESTION_STOPWORDS
    }


def rank_contexts_for_scoring(question, contexts):
    keywords = extract_question_keywords(question)
    if not keywords:
        return list(contexts)

    ranked = []
    for index, context in enumerate(contexts):
        context_text = str(context)
        context_tokens = set(re.findall(r"[a-z0-9_]+", context_text.lower()))
        overlap = len(keywords & context_tokens)
        ranked.append((overlap, len(context_text), index, context))

    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [context for _, _, _, context in ranked]


def limit_contexts_for_scoring(question, contexts, max_candidates=None):
    if max_candidates is None or max_candidates <= 0 or len(contexts) <= max_candidates:
        return list(contexts)

    ranked_contexts = rank_contexts_for_scoring(question, contexts)
    return ranked_contexts[:max_candidates]
