import asyncio

from typesafe_sdk import AsyncTypeSafeClient, Noul

from app.core.config import get_settings


async def main() -> None:
    settings = get_settings()
    if not settings.typesafe_api_key:
        raise SystemExit("TYPESAFE_API_KEY is missing from .env")

    try:
        async with AsyncTypeSafeClient(
            api_key=settings.typesafe_api_key,
            model=settings.typesafe_model,
        ) as client:
            response = await client.system_one(
                state={"message": "This is a Jev API key connectivity test."},
                questions={
                    "is_test": Noul(instructions="Is this message explicitly a test?")
                },
            )
    except Exception as exc:
        raise SystemExit(f"Jev key test failed: {exc}") from exc

    answer = response.answers["is_test"]
    print(f"Jev key is valid. model={response.model}, probability={answer.noul:.3f}")


if __name__ == "__main__":
    asyncio.run(main())
