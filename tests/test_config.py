"""
test_config.py — Tests for mmi.config constants and logger factory.
"""
import logging
from pathlib import Path

import mmi.config as config


class TestConstants:
    def test_output_dir_is_path(self):
        assert isinstance(config.MMI_OUTPUT_DIR, Path)

    def test_debug_dir_is_subdir_of_output(self):
        assert config.MMI_DEBUG_DIR == config.MMI_OUTPUT_DIR / "debug"

    def test_db_path_is_in_output_dir(self):
        assert config.MMI_DB_PATH == config.MMI_OUTPUT_DIR / "mmi_history.db"

    def test_chrome_user_agent_has_chrome(self):
        assert "Chrome" in config.CHROME_USER_AGENT

    def test_chrome_user_agent_starts_with_mozilla(self):
        assert config.CHROME_USER_AGENT.startswith("Mozilla/5.0")


class TestGetLogger:
    def test_returns_logger(self):
        logger = config.get_logger("test.config.returns")
        assert isinstance(logger, logging.Logger)

    def test_verbose_sets_debug_level(self):
        logger = config.get_logger("test.config.verbose", verbose=True)
        assert logger.level == logging.DEBUG

    def test_default_sets_info_level(self):
        logger = config.get_logger("test.config.default", verbose=False)
        assert logger.level == logging.INFO

    def test_has_stream_handler(self):
        logger = config.get_logger("test.config.handler")
        assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)

    def test_idempotent_handlers(self):
        # Calling twice with the same name should not add duplicate handlers
        name = "test.config.idempotent"
        config.get_logger(name)
        logger = config.get_logger(name)
        stream_handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
        assert len(stream_handlers) == 1

    def test_level_updated_on_second_call(self):
        # Second call changes the level even if handler already exists
        name = "test.config.level_update"
        config.get_logger(name, verbose=False)
        logger = config.get_logger(name, verbose=True)
        assert logger.level == logging.DEBUG

    def test_different_names_are_independent(self):
        a = config.get_logger("test.config.indep_a", verbose=True)
        b = config.get_logger("test.config.indep_b", verbose=False)
        assert a.level != b.level
