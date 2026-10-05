from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from projectctl.core.errors import ProviderUnavailableError, TaskStoreError
from projectctl.integrations.linear.team import normalize_linear_team_id


LINEAR_GRAPHQL_ENDPOINT = "https://api.linear.app/graphql"
LINEAR_GRAPHQL_CONTRACT = "linear-graphql-v2"


_TEAM_QUERY = """
query ProjectCtlLinearTeam($teamId: String!) {
  team(id: $teamId) {
    id
    name
  }
}
"""

_ISSUES_QUERY = """
query ProjectCtlLinearIssues($teamId: String!, $first: Int!, $after: String) {
  team(id: $teamId) {
    id
    name
    issues(first: $first, after: $after, orderBy: updatedAt) {
      nodes {
        id
        identifier
        title
        priority
        createdAt
        updatedAt
        archivedAt
        state {
          id
          name
          type
        }
        assignee {
          id
          name
        }
        parent {
          id
          identifier
          team {
            id
          }
        }
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""



_INVERSE_RELATIONS_QUERY = """
query ProjectCtlLinearInverseRelations(
  $issueId: String!,
  $first: Int!,
  $after: String
) {
  issue(id: $issueId) {
    id
    inverseRelations(first: $first, after: $after) {
      nodes {
        id
        type
        issue {
          id
          identifier
          state {
            type
          }
          team {
            id
          }
        }
        relatedIssue {
          id
          identifier
          state {
            type
          }
          team {
            id
          }
        }
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""

class LinearIssuesClient:
    """Narrow read-only Linear GraphQL client for M3.2a/M3.2b.

    M3.2b adds independently paginated incoming IssueRelation reads so blocker
    semantics are not truncated inside the team Issue connection.

    Credentials remain outside ProjectCTL persisted state. Personal API keys are
    read from LINEAR_API_KEY and OAuth access tokens from LINEAR_ACCESS_TOKEN.
    """

    def __init__(
        self,
        project_root: Path,
        *,
        team_id: str,
        api_key: str | None = None,
        access_token: str | None = None,
        endpoint: str = LINEAR_GRAPHQL_ENDPOINT,
        timeout_seconds: int = 30,
    ):
        self.project_root = project_root.resolve()
        self.team_id = normalize_linear_team_id(team_id)
        if self.team_id is None:
            raise TaskStoreError("Linear task authority requires a team UUID.")

        key = api_key if api_key is not None else os.environ.get("LINEAR_API_KEY")
        token = (
            access_token
            if access_token is not None
            else os.environ.get("LINEAR_ACCESS_TOKEN")
        )
        if key and token:
            raise ProviderUnavailableError(
                "Configure only one Linear credential source: "
                "LINEAR_API_KEY or LINEAR_ACCESS_TOKEN."
            )
        if key:
            self.authorization = key.strip()
        elif token:
            self.authorization = f"Bearer {token.strip()}"
        else:
            raise ProviderUnavailableError(
                "Linear task authority requires LINEAR_API_KEY or "
                "LINEAR_ACCESS_TOKEN in the environment."
            )
        if not self.authorization or self.authorization == "Bearer ":
            raise ProviderUnavailableError("Linear credential is empty.")

        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    def _http_post(self, body: bytes) -> tuple[int, bytes]:
        request = Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": self.authorization,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "projectctl-linear-read-authority",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return int(response.status), response.read()
        except HTTPError as exc:
            payload = exc.read()
            message = payload.decode("utf-8", errors="replace")[:500]
            raise TaskStoreError(
                f"Linear GraphQL HTTP request failed with status {exc.code}: {message}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise TaskStoreError(f"Linear GraphQL request failed: {exc}") from exc

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(
            {"query": query, "variables": variables},
            sort_keys=True,
        ).encode("utf-8")
        status, raw = self._http_post(body)
        if status != 200:
            raise TaskStoreError(f"Linear GraphQL returned HTTP {status}.")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TaskStoreError("Linear GraphQL returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise TaskStoreError("Linear GraphQL response must be a JSON object.")

        errors = payload.get("errors")
        if errors:
            messages: list[str] = []
            if isinstance(errors, list):
                for item in errors:
                    if isinstance(item, dict):
                        messages.append(str(item.get("message") or "unknown GraphQL error"))
                    else:
                        messages.append(str(item))
            else:
                messages.append(str(errors))
            raise TaskStoreError(
                "Linear GraphQL returned errors: " + "; ".join(messages[:5])
            )

        data = payload.get("data")
        if not isinstance(data, dict):
            raise TaskStoreError("Linear GraphQL response is missing a data object.")
        return data

    def team_info(self) -> dict[str, Any]:
        data = self._graphql(_TEAM_QUERY, {"teamId": self.team_id})
        team = data.get("team")
        if not isinstance(team, dict):
            raise TaskStoreError(
                f"Linear team {self.team_id!r} was not found or is not readable."
            )
        if str(team.get("id") or "").strip() != self.team_id:
            raise TaskStoreError("Linear team response identity does not match config.")
        return team

    def list_all(self, *, page_size: int = 50) -> list[dict[str, Any]]:
        if page_size <= 0:
            raise ValueError("Linear page_size must be positive.")

        after: str | None = None
        issues: list[dict[str, Any]] = []
        seen_cursors: set[str] = set()

        while True:
            data = self._graphql(
                _ISSUES_QUERY,
                {
                    "teamId": self.team_id,
                    "first": page_size,
                    "after": after,
                },
            )
            team = data.get("team")
            if not isinstance(team, dict):
                raise TaskStoreError(
                    f"Linear team {self.team_id!r} was not found or is not readable."
                )
            if str(team.get("id") or "").strip() != self.team_id:
                raise TaskStoreError("Linear issue page belongs to an unexpected team.")

            connection = team.get("issues")
            if not isinstance(connection, dict):
                raise TaskStoreError("Linear team issue connection is missing.")
            nodes = connection.get("nodes")
            page_info = connection.get("pageInfo")
            if not isinstance(nodes, list) or not isinstance(page_info, dict):
                raise TaskStoreError("Linear issue page has an invalid connection shape.")
            for node in nodes:
                if not isinstance(node, dict):
                    raise TaskStoreError("Linear issue page contains a non-object node.")
                issues.append(node)

            has_next = page_info.get("hasNextPage")
            if not isinstance(has_next, bool):
                raise TaskStoreError("Linear pageInfo.hasNextPage is not boolean.")
            if not has_next:
                return issues

            cursor = page_info.get("endCursor")
            if not isinstance(cursor, str) or not cursor.strip():
                raise TaskStoreError(
                    "Linear pagination hasNextPage=true without a usable endCursor."
                )
            if cursor in seen_cursors:
                raise TaskStoreError("Linear pagination cursor repeated; refusing a loop.")
            seen_cursors.add(cursor)
            after = cursor


    def list_inverse_relations(
        self,
        issue_id: str,
        *,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        """Return relations whose target is the requested issue.

        For Linear `type=blocks`, the source `issue` is the blocker and the
        target `relatedIssue` is blocked. ProjectCTL validates that the target
        UUID on every relation equals `issue_id` before using it.
        """
        requested = str(issue_id).strip()
        if not requested:
            raise ValueError("Linear issue_id must be non-empty.")
        if page_size <= 0:
            raise ValueError("Linear page_size must be positive.")

        after: str | None = None
        relations: list[dict[str, Any]] = []
        seen_cursors: set[str] = set()

        while True:
            data = self._graphql(
                _INVERSE_RELATIONS_QUERY,
                {
                    "issueId": requested,
                    "first": page_size,
                    "after": after,
                },
            )
            issue = data.get("issue")
            if not isinstance(issue, dict):
                raise TaskStoreError(
                    f"Linear issue {requested!r} was not found or is not readable."
                )
            if str(issue.get("id") or "").strip() != requested:
                raise TaskStoreError(
                    "Linear inverse-relation response identity does not match request."
                )

            connection = issue.get("inverseRelations")
            if not isinstance(connection, dict):
                raise TaskStoreError(
                    "Linear issue inverseRelations connection is missing."
                )
            nodes = connection.get("nodes")
            page_info = connection.get("pageInfo")
            if not isinstance(nodes, list) or not isinstance(page_info, dict):
                raise TaskStoreError(
                    "Linear inverseRelations page has an invalid connection shape."
                )
            for node in nodes:
                if not isinstance(node, dict):
                    raise TaskStoreError(
                        "Linear inverseRelations page contains a non-object node."
                    )
                relations.append(node)

            has_next = page_info.get("hasNextPage")
            if not isinstance(has_next, bool):
                raise TaskStoreError(
                    "Linear inverseRelations pageInfo.hasNextPage is not boolean."
                )
            if not has_next:
                return relations

            cursor = page_info.get("endCursor")
            if not isinstance(cursor, str) or not cursor.strip():
                raise TaskStoreError(
                    "Linear inverseRelations hasNextPage=true without a usable endCursor."
                )
            if cursor in seen_cursors:
                raise TaskStoreError(
                    "Linear inverseRelations cursor repeated; refusing a loop."
                )
            seen_cursors.add(cursor)
            after = cursor

    def version(self) -> str:
        return LINEAR_GRAPHQL_CONTRACT
