"""Phase 2: Database CRUD tests for models and agents."""
import os
import sys
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "app"))

from core.database import Base
from models.records import ModelRecord, AgentRecord


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


class TestModelCRUD:
    """CRUD tests for the models table."""

    def test_create_model(self, db_session):
        """Should create a new model record."""
        model = ModelRecord(
            name="llama-2-7b",
            provider="huggingface",
            path="/models/llama-2-7b",
            size="13GB",
            status="available",
        )
        db_session.add(model)
        db_session.commit()

        assert model.id is not None
        assert model.name == "llama-2-7b"

    def test_read_model(self, db_session):
        """Should read a model record by id."""
        model = ModelRecord(name="gpt-neo", provider="local")
        db_session.add(model)
        db_session.commit()

        fetched = db_session.query(ModelRecord).filter_by(id=model.id).first()
        assert fetched is not None
        assert fetched.name == "gpt-neo"
        assert fetched.provider == "local"

    def test_update_model(self, db_session):
        """Should update a model record."""
        model = ModelRecord(name="old-name", status="downloading")
        db_session.add(model)
        db_session.commit()

        model.name = "new-name"
        model.status = "available"
        db_session.commit()

        fetched = db_session.query(ModelRecord).filter_by(id=model.id).first()
        assert fetched.name == "new-name"
        assert fetched.status == "available"

    def test_delete_model(self, db_session):
        """Should delete a model record."""
        model = ModelRecord(name="to-delete")
        db_session.add(model)
        db_session.commit()
        mid = model.id

        db_session.delete(model)
        db_session.commit()

        fetched = db_session.query(ModelRecord).filter_by(id=mid).first()
        assert fetched is None

    def test_list_models(self, db_session):
        """Should list all models."""
        db_session.add_all([
            ModelRecord(name="m1", provider="hf"),
            ModelRecord(name="m2", provider="ms"),
        ])
        db_session.commit()

        models = db_session.query(ModelRecord).all()
        assert len(models) == 2


class TestAgentCRUD:
    """CRUD tests for the agents table."""

    def test_create_agent(self, db_session):
        """Should create a new agent record."""
        agent = AgentRecord(
            name="my-agent",
            model="llama-2-7b",
            tools='["file_read", "code_search"]',
            memory='{"type": "conversation"}',
        )
        db_session.add(agent)
        db_session.commit()

        assert agent.id is not None
        assert agent.name == "my-agent"

    def test_read_agent(self, db_session):
        """Should read an agent by name."""
        agent = AgentRecord(name="helper", model="gpt-4")
        db_session.add(agent)
        db_session.commit()

        fetched = db_session.query(AgentRecord).filter_by(name="helper").first()
        assert fetched is not None
        assert fetched.model == "gpt-4"

    def test_update_agent(self, db_session):
        """Should update agent config."""
        agent = AgentRecord(name="bot", model="old-model")
        db_session.add(agent)
        db_session.commit()

        agent.model = "new-model"
        agent.tools = '["search"]'
        db_session.commit()

        fetched = db_session.query(AgentRecord).filter_by(id=agent.id).first()
        assert fetched.model == "new-model"
        assert fetched.tools == '["search"]'

    def test_delete_agent(self, db_session):
        """Should delete an agent."""
        agent = AgentRecord(name="del-me", model="x")
        db_session.add(agent)
        db_session.commit()
        aid = agent.id

        db_session.delete(agent)
        db_session.commit()

        fetched = db_session.query(AgentRecord).filter_by(id=aid).first()
        assert fetched is None

    def test_list_agents(self, db_session):
        """Should list all agents."""
        db_session.add_all([
            AgentRecord(name="a1", model="m1"),
            AgentRecord(name="a2", model="m2"),
        ])
        db_session.commit()

        agents = db_session.query(AgentRecord).all()
        assert len(agents) == 2
