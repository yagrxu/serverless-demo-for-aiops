"""SigV4 request signing for AWS API calls."""
from __future__ import annotations

import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials


def sign(
    request: httpx.Request,
    service: str,
    region: str,
    credentials: Credentials,
) -> httpx.Request:
    """Sign an httpx Request with SigV4.

    Mutates the request headers in-place and returns it.
    """
    # Convert httpx.Request to botocore AWSRequest
    aws_request = AWSRequest(
        method=request.method,
        url=str(request.url),
        headers=dict(request.headers),
        data=request.content,
    )

    SigV4Auth(credentials, service, region).add_auth(aws_request)

    # Copy signed headers back to the httpx request
    for key, value in aws_request.headers.items():
        request.headers[key] = value

    return request
