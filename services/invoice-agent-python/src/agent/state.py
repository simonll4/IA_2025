from typing import Any, Dict, List, Optional, TypedDict


class Turn(TypedDict):
    role: str
    content: str


class InvoiceAgentState(TypedDict, total=False):
    """Estado de trabajo compartido entre nodos del grafo."""

    question: str
    history: List[Turn]
    schema: Optional[Any]
    plan: Optional[str]
    sql_query: Optional[str]
    sql_result: Optional[List[Dict[str, Any]]]
    error: Optional[str]
    needs_clarification: bool
    clarification_question: Optional[str]
    session_id: Optional[str]


