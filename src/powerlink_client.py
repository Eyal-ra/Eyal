from dataclasses import dataclass
from typing import Optional


@dataclass
class PowerlinkCustomer:
    customer_number: str
    full_name: str
    phone: str
    id_number: str
    raw: dict


class PowerlinkClient:
    """
    Stub implementation - REPLACE with real Powerlink API calls
    once we have the API docs and a working token.
    Expected endpoints (typical CRM REST shape):
      GET  /customers?phone=...&idNumber=...
      PATCH /customers/{customer_number}  body={"fullName": "..."}
    """

    def __init__(self, api_url: str, api_token: str, fields: dict):
        self.api_url = api_url.rstrip("/")
        self.api_token = api_token
        self.fields = fields

    def find_customer(self, phone: str, id_number: str) -> Optional[PowerlinkCustomer]:
        raise NotImplementedError("Powerlink find_customer - fill in once API docs are available")

    def update_full_name(self, customer_number: str, new_full_name: str) -> None:
        raise NotImplementedError("Powerlink update_full_name - fill in once API docs are available")
