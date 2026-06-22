"""Station and topology schemas."""

from pydantic import BaseModel


class ChannelMap(BaseModel):
    """Named DUT terminal to instrument channel mapping."""

    terminal: str
    channel: int
    role: str


class StationProfile(BaseModel):
    """Shareable station profile schema."""

    name: str
    gpib_address: int = 17
    channels: list[ChannelMap] = []
