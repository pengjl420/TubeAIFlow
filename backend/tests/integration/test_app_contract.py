import unittest

from app.main import app


class ProductionAppContractTests(unittest.TestCase):
    def test_project_workflow_and_compatible_tools_are_registered(self) -> None:
        paths = {route.path for route in app.routes}

        required = {
            "/api/health",
            "/api/projects",
            "/api/projects/{project_id}/script",
            "/api/projects/{project_id}/workflows/narration/start",
            "/api/projects/{project_id}/tasks/status",
            "/api/projects/{project_id}/quality/check",
            "/api/providers",
            "/api/tools/voice-generation/tasks",
            "/api/tools/local-video-merge/tasks",
            "/api/avatars/tasks",
        }
        self.assertTrue(required.issubset(paths), required - paths)

    def test_brand_and_development_mode_are_exposed_by_health(self) -> None:
        response = next(route for route in app.routes if route.path == "/api/health").endpoint()

        self.assertEqual(response["data"]["product"], "TubeAiFolw")
        self.assertEqual(response["data"]["mode"], "local-web-development")


if __name__ == "__main__":
    unittest.main()
