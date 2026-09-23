import argparse
import json
import os

import pika


RABBITMQ_URL = os.getenv(
    "RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/%2F"
)
QUEUE_NAME = os.getenv("RABBITMQ_QUEUE", "crawler")


def enqueue_url(url: str) -> None:
    # The consumer records visited URLs when it processes them.
    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    try:
        channel = connection.channel()
        channel.queue_declare(queue=QUEUE_NAME, durable=True)
        channel.basic_publish(
            exchange="",
            routing_key=QUEUE_NAME,
            body=json.dumps({"url": url}),
            properties=pika.BasicProperties(
                delivery_mode=pika.DeliveryMode.Persistent,
                content_type="application/json",
            ),
        )
    finally:
        connection.close()


def run_cli() -> None:
    parser = argparse.ArgumentParser(description="Publish an initial crawler URL")
    parser.add_argument("url", help="Initial HTTP(S) URL to crawl")
    arguments = parser.parse_args()
    enqueue_url(arguments.url)
    print(f"Published {arguments.url} to queue {QUEUE_NAME}")


if __name__ == "__main__":
    run_cli()
