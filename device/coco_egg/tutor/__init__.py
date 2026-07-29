"""The tutor's front door: route a turn to the quiz, a joke, or the model."""
from . import llama_client, quiz, jokes      # noqa: F401  (llama_client first)
from .llama_client import forget as _forget_history
from .llama_client import is_opener, remember, warm  # noqa: F401


def stream_sentences(question: str, cfg: dict):
    """Reply sentences for one learner turn.

    Order is load-bearing, and both branches beat the model for the same
    reason: the interesting part is SELECTION, not generation, and a 1.7B is
    poor at selection. Asked for a joke it tells the same joke; asked to play it
    would be answered as a greeting.

    The quiz goes first because while a game is running every turn belongs to
    it — "another one" is a request for the next question, not for a joke, and
    an answer like "twenty seven" is not something to retrieve against. "Let's
    play a quiz" also matches is_opener() exactly, so leaving either to the
    model would answer a request to play with an invitation to ask a question.
    """
    if quiz.active() or quiz.is_start(question):
        return quiz.turn(question, cfg)
    if jokes.is_request(question):
        return jokes.tell(cfg)
    return llama_client.stream_sentences(question, cfg)


def forget() -> None:
    """Drop everything a new learner must not inherit: history, a live game,
    and the "another one" context.

    Note what is NOT dropped — the joke and quiz decks. Those are the memory of
    what has already been told, which is the whole point of them, and a new
    learner at the same party should not be told the joke the last one just
    heard.
    """
    _forget_history()
    quiz.reset()
    jokes.reset()
