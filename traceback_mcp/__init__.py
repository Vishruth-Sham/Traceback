"""Thin stdio MCP adapter for the Traceback local REST API.

This package never imports backend/processor/database modules and never
opens a direct PostgreSQL connection. Every tool call is translated into an
authenticated HTTP request against the loopback FastAPI REST API, which
remains the sole writer and the sole source of business rules, canonical
IDs, versions, and errors. See docs/mcp-adapter.md for the tool catalog and
docs/local-development.md for Codex/Claude Code stdio configuration.
"""
