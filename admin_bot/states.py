"""Admin bot conversational states."""
from aiogram.fsm.state import State, StatesGroup


class AdminStates(StatesGroup):
    waiting_customer_id = State()
