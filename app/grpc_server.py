import asyncio
import logging

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from grpc_reflection.v1alpha import reflection

import rag_pb2
import rag_pb2_grpc
from app.config import settings
from app.dependencies import init_resources
from app.grpc_handlers import RagServiceServicer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def serve() -> None:
    await init_resources()

    server = grpc.aio.server()

    # RagService 등록
    rag_pb2_grpc.add_RagServiceServicer_to_server(RagServiceServicer(), server)

    # Health check
    health_servicer = health.aio.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    await health_servicer.set(
        "myrag.v1.RagService",
        health_pb2.HealthCheckResponse.SERVING,
    )

    # Reflection (개발/디버깅용)
    service_names = (
        rag_pb2.DESCRIPTOR.services_by_name["RagService"].full_name,
        health_pb2.DESCRIPTOR.services_by_name["Health"].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(service_names, server)

    listen_addr = f"[::]:{settings.grpc_port}"
    server.add_insecure_port(listen_addr)

    logger.info("gRPC server starting on %s", listen_addr)
    await server.start()
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
