from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MarketId:
    dex: str
    coin: str

    def __post_init__(self) -> None:
        if not self.coin.strip():
            raise ValueError("coin must not be empty")

    @property
    def canonical(self) -> str:
        return f"{self.dex}:{self.coin}" if self.dex else self.coin
