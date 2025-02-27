import unittest
from http.server import BaseHTTPRequestHandler
from test.utils import GraphHelper
from test.utils.httpservermock import (
    MethodName,
    MockHTTPResponse,
    ServedBaseHTTPServerMock,
    ctx_http_server,
)
from urllib.error import HTTPError

from rdflib import Graph, Namespace

"""
Test that correct content negotiation headers are passed
by graph.parse
"""


xmltestdoc = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF
   xmlns="http://example.org/"
   xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
>
  <rdf:Description rdf:about="http://example.org/a">
    <b rdf:resource="http://example.org/c"/>
  </rdf:Description>
</rdf:RDF>
"""

n3testdoc = """@prefix : <http://example.org/> .

:a :b :c .
"""

nttestdoc = "<http://example.org/a> <http://example.org/b> <http://example.org/c> .\n"

ttltestdoc = """@prefix : <http://example.org/> .

            :a :b :c .
            """

jsonldtestdoc = """
                [
                  {
                    "@id": "http://example.org/a",
                    "http://example.org/b": [
                      {
                        "@id": "http://example.org/c"
                      }
                    ]
                  }
                ]
                """


class ContentNegotiationHandler(BaseHTTPRequestHandler):
    def do_GET(self):

        self.send_response(200, "OK")
        # fun fun fun parsing accept header.

        acs = self.headers["Accept"].split(",")
        acq = [x.split(";") for x in acs if ";" in x]
        acn = [(x, "q=1") for x in acs if ";" not in x]
        acs = [(x[0].strip(), float(x[1].strip()[2:])) for x in acq + acn]
        ac = sorted(acs, key=lambda x: x[1])
        ct = ac[-1]

        if "application/rdf+xml" in ct:
            rct = "application/rdf+xml"
            content = xmltestdoc
        elif "text/n3" in ct:
            rct = "text/n3"
            content = n3testdoc
        elif "application/trig" in ct:
            rct = "application/trig"
            content = ttltestdoc
        elif "text/plain" in ct or "application/n-triples" in ct:
            rct = "text/plain"
            content = nttestdoc
        elif "application/ld+json" in ct:
            rct = "application/ld+json"
            content = jsonldtestdoc
        else:  # "text/turtle" in ct:
            rct = "text/turtle"
            content = ttltestdoc

        self.send_header("Content-type", rct)
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def log_message(self, *args):
        pass


class TestGraphHTTP(unittest.TestCase):
    def test_content_negotiation(self) -> None:
        EG = Namespace("http://example.org/")
        expected = Graph()
        expected.add((EG.a, EG.b, EG.c))
        expected_triples = GraphHelper.triple_set(expected)

        with ctx_http_server(ContentNegotiationHandler) as server:
            (host, port) = server.server_address
            url = f"http://{host}:{port}/foo"
            for format in ("xml", "n3", "nt"):
                graph = Graph()
                graph.parse(url, format=format)
                self.assertEqual(expected_triples, GraphHelper.triple_set(graph))

    def test_content_negotiation_no_format(self) -> None:
        EG = Namespace("http://example.org/")
        expected = Graph()
        expected.add((EG.a, EG.b, EG.c))
        expected_triples = GraphHelper.triple_set(expected)

        with ctx_http_server(ContentNegotiationHandler) as server:
            (host, port) = server.server_address
            url = f"http://{host}:{port}/foo"
            graph = Graph()
            graph.parse(url)
            self.assertEqual(expected_triples, GraphHelper.triple_set(graph))

    def test_source(self) -> None:
        EG = Namespace("http://example.org/")
        expected = Graph()
        expected.add((EG["a"], EG["b"], EG["c"]))
        expected_triples = GraphHelper.triple_set(expected)

        with ServedBaseHTTPServerMock() as httpmock:
            url = httpmock.url

            httpmock.responses[MethodName.GET].append(
                MockHTTPResponse(
                    200,
                    "OK",
                    f"<{EG['a']}> <{EG['b']}> <{EG['c']}>.".encode(),
                    {"Content-Type": ["text/turtle"]},
                )
            )
            graph = Graph()
            graph.parse(source=url)
            self.assertEqual(expected_triples, GraphHelper.triple_set(graph))

    def test_3xx(self) -> None:
        EG = Namespace("http://example.com/")
        expected = Graph()
        expected.add((EG["a"], EG["b"], EG["c"]))
        expected_triples = GraphHelper.triple_set(expected)

        with ServedBaseHTTPServerMock() as httpmock:
            url = httpmock.url

            for idx in range(3):
                httpmock.responses[MethodName.GET].append(
                    MockHTTPResponse(
                        302,
                        "FOUND",
                        "".encode(),
                        {"Location": [f"{url}/loc/302/{idx}"]},
                    )
                )
            for idx in range(3):
                httpmock.responses[MethodName.GET].append(
                    MockHTTPResponse(
                        303,
                        "See Other",
                        "".encode(),
                        {"Location": [f"{url}/loc/303/{idx}"]},
                    )
                )
            for idx in range(3):
                httpmock.responses[MethodName.GET].append(
                    MockHTTPResponse(
                        308,
                        "Permanent Redirect",
                        "".encode(),
                        {"Location": [f"{url}/loc/308/{idx}"]},
                    )
                )

            httpmock.responses[MethodName.GET].append(
                MockHTTPResponse(
                    200,
                    "OK",
                    f"<{EG['a']}> <{EG['b']}> <{EG['c']}>.".encode(),
                    {"Content-Type": ["text/turtle"]},
                )
            )

            graph = Graph()
            graph.parse(location=url, format="turtle")
            self.assertEqual(expected_triples, GraphHelper.triple_set(graph))

            httpmock.mocks[MethodName.GET].assert_called()
            assert len(httpmock.requests[MethodName.GET]) == 10
            for request in httpmock.requests[MethodName.GET]:
                self.assertRegex(request.headers.get("Accept"), "text/turtle")

            request_paths = [
                request.path for request in httpmock.requests[MethodName.GET]
            ]
            self.assertEqual(
                request_paths,
                [
                    "/",
                    "/loc/302/0",
                    "/loc/302/1",
                    "/loc/302/2",
                    "/loc/303/0",
                    "/loc/303/1",
                    "/loc/303/2",
                    "/loc/308/0",
                    "/loc/308/1",
                    "/loc/308/2",
                ],
            )

    def test_5xx(self):
        with ServedBaseHTTPServerMock() as httpmock:
            url = httpmock.url
            httpmock.responses[MethodName.GET].append(
                MockHTTPResponse(500, "Internal Server Error", "".encode(), {})
            )

            graph = Graph()

            with self.assertRaises(HTTPError) as raised:
                graph.parse(location=url, format="turtle")

            self.assertEqual(raised.exception.code, 500)


if __name__ == "__main__":
    unittest.main()
