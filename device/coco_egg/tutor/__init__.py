"""The tutor's front door: route a turn to the quiz or to the model."""
from . import llama_client, quiz          # noqa: F401  (order: quiz imports llama_client)
from .llama_client import forget as _forget_history
from .llama_client import is_opener, remember, warm  # noqa: F401


def stream_sentences(question: str, cfg: dict):
    """Reply sentences for one learner turn.

    The quiz is checked FIRST and it is not a subtlety: "let's play a quiz"
    matches llama_client.is_opener() exactly (a proposal with no interrogative),
    so leaving it to the model would answer a request to play with a friendly
    invitation to ask a question instead. While a game is running every turn
    belongs to it — an answer like "twenty seven" is not a question to retrieve
    against.
    """
    if quiz.active() or quiz.is_start(question):
        return quiz.turn(question, cfg)
    return llama_client.stream_sentences(question, cfg)


def forget() -> None:
    """Drop everything a new learner must not inherit: history AND a live game."""
    _forget_history()
    quiz.reset()
