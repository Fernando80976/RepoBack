from app.utils.flatten_data import flatten_mission_data

def test_flatten_mission_data_basic():
    item = {
        "id": 123,
        "status": "active",
        "current_progress": 2,
        "started_at": "2024-01-01",
        "completed_at": None,
        "missions": {
            "id": 10,
            "title": "Test Mission",
            "description": "Desc",
            "mission_type": "main",
            "target_type": "kill",
            "target_value": 5,
            "reward_exp": 100,
            "reward_gold": 50,
            "reward_items": ["potion"]
        }
    }
    result = flatten_mission_data(item)
    assert result["instance_id"] == 123
    assert result["mission_id"] == 10
    assert result["title"] == "Test Mission"
    assert result["reward_items"] == ["potion"]
    assert result["daily_target_id"] is None

def test_flatten_mission_data_daily():
    item = {
        "id": 1,
        "status": "active",
        "current_progress": 0,
        "started_at": "2024-01-01",
        "completed_at": None,
        "missions": {
            "id": 2,
            "title": "Daily",
            "description": "Daily desc",
            "mission_type": "daily",
            "target_type": "dle_guess",
            "target_value": 1,
            "reward_exp": 10,
            "reward_gold": 5,
            "reward_items": []
        }
    }
    result = flatten_mission_data(item, target_today_id=42)
    assert result["daily_target_id"] == 42
