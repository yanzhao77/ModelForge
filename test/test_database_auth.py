"""
测试数据库和用户认证功能
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_manager import DatabaseManager
from api.auth_service import AuthService
from api.session_service import SessionService
from api.memory_service import MemoryService


def test_database_init():
    """测试数据库初始化"""
    print("=" * 50)
    print("测试 1: 数据库初始化")
    print("=" * 50)
    
    db_manager = DatabaseManager()
    print(f"✓ 数据库路径: {db_manager.db_path}")
    print(f"✓ 数据库初始化成功")
    return db_manager


def test_user_registration(db_manager):
    """测试用户注册"""
    print("\n" + "=" * 50)
    print("测试 2: 用户注册")
    print("=" * 50)
    
    with db_manager.get_session() as db:
        # 注册测试用户
        success, message, user = AuthService.register_user(
            db,
            username="test_user",
            password="test123456",
            email="test@example.com"
        )
        
        if success:
            print(f"✓ 用户注册成功: {user.username}")
            print(f"  - 用户ID: {user.id}")
            print(f"  - 邮箱: {user.email}")
            print(f"  - 创建时间: {user.created_at}")
            return user.id
        else:
            print(f"✗ 注册失败: {message}")
            # 如果用户已存在，获取用户ID
            existing_user = AuthService.get_user_by_username(db, "test_user")
            if existing_user:
                print(f"  使用现有用户: {existing_user.id}")
                return existing_user.id
            return None


def test_user_login(db_manager):
    """测试用户登录"""
    print("\n" + "=" * 50)
    print("测试 3: 用户登录")
    print("=" * 50)
    
    with db_manager.get_session() as db:
        success, message, user, token = AuthService.login_user(
            db,
            username="test_user",
            password="test123456"
        )
        
        if success:
            print(f"✓ 登录成功: {user.username}")
            print(f"  - Token: {token[:50]}...")
            print(f"  - 最后登录: {user.last_login}")
            return user.id, token
        else:
            print(f"✗ 登录失败: {message}")
            return None, None


def test_token_verification(token):
    """测试 Token 验证"""
    print("\n" + "=" * 50)
    print("测试 4: Token 验证")
    print("=" * 50)
    
    payload = AuthService.verify_token(token)
    if payload:
        print(f"✓ Token 验证成功")
        print(f"  - 用户ID: {payload['user_id']}")
        print(f"  - 用户名: {payload['username']}")
        print(f"  - 过期时间: {payload['exp']}")
    else:
        print(f"✗ Token 验证失败")


def test_session_management(db_manager, user_id):
    """测试会话管理"""
    print("\n" + "=" * 50)
    print("测试 5: 会话管理")
    print("=" * 50)
    
    with db_manager.get_session() as db:
        # 创建会话
        session1 = SessionService.create_session(db, user_id, "测试会话 1")
        print(f"✓ 创建会话 1: ID={session1.id}, 标题={session1.title}")
        
        session2 = SessionService.create_session(db, user_id, "测试会话 2")
        print(f"✓ 创建会话 2: ID={session2.id}, 标题={session2.title}")
        
        # 获取用户所有会话
        sessions = SessionService.get_user_sessions(db, user_id)
        print(f"✓ 用户共有 {len(sessions)} 个会话")
        
        return session1.id, session2.id


def test_message_management(db_manager, session_id):
    """测试消息管理"""
    print("\n" + "=" * 50)
    print("测试 6: 消息管理")
    print("=" * 50)
    
    with db_manager.get_session() as db:
        # 添加消息
        msg1 = SessionService.add_message(db, session_id, "user", "你好，我是测试用户")
        print(f"✓ 添加用户消息: {msg1.content[:30]}")
        
        msg2 = SessionService.add_message(db, session_id, "assistant", "你好！我是 AI 助手，很高兴为您服务。")
        print(f"✓ 添加助手消息: {msg2.content[:30]}")
        
        # 获取会话消息
        messages = SessionService.get_session_messages(db, session_id)
        print(f"✓ 会话共有 {len(messages)} 条消息")
        
        # 获取会话历史
        history = SessionService.get_session_history(db, session_id)
        print(f"✓ 会话历史格式化成功，共 {len(history)} 条")
        for h in history:
            print(f"  - {h['role']}: {h['content'][:30]}...")


def test_memory_management(db_manager, user_id, session_id):
    """测试记忆管理"""
    print("\n" + "=" * 50)
    print("测试 7: 记忆管理")
    print("=" * 50)
    
    with db_manager.get_session() as db:
        # 创建记忆
        memory1 = MemoryService.create_memory(
            db, user_id,
            memory_type=MemoryService.MEMORY_TYPE_PREFERENCE,
            key="喜欢",
            value="我喜欢使用 Python 编程",
            source_session_id=session_id,
            importance=0.9
        )
        print(f"✓ 创建偏好记忆: {memory1.value}")
        
        memory2 = MemoryService.create_memory(
            db, user_id,
            memory_type=MemoryService.MEMORY_TYPE_FACT,
            key="我是",
            value="我是一名 AI 开发者",
            source_session_id=session_id,
            importance=0.95
        )
        print(f"✓ 创建事实记忆: {memory2.value}")
        
        # 从消息中提取记忆
        test_message = "我喜欢在周末看电影，我的工作是软件工程师"
        extracted = MemoryService.extract_memories_from_message(
            db, user_id, test_message, session_id
        )
        print(f"✓ 从消息中提取了 {len(extracted)} 条记忆")
        
        # 搜索记忆
        memories = MemoryService.search_memories(db, user_id, "Python")
        print(f"✓ 搜索 'Python' 找到 {len(memories)} 条记忆")
        
        # 获取相关记忆
        relevant = MemoryService.get_relevant_memories_for_query(
            db, user_id, "我想学习编程"
        )
        print(f"✓ 查询相关记忆找到 {len(relevant)} 条")
        
        # 格式化记忆
        context = MemoryService.format_memories_for_context(relevant)
        print(f"✓ 记忆上下文格式化成功:")
        print(context)


def test_session_operations(db_manager, session_id):
    """测试会话操作"""
    print("\n" + "=" * 50)
    print("测试 8: 会话操作")
    print("=" * 50)
    
    with db_manager.get_session() as db:
        # 自动生成标题
        success = SessionService.auto_generate_title(db, session_id)
        if success:
            session = SessionService.get_session_by_id(db, session_id)
            print(f"✓ 自动生成标题: {session.title}")
        
        # 更新标题
        SessionService.update_session_title(db, session_id, "更新后的标题")
        session = SessionService.get_session_by_id(db, session_id)
        print(f"✓ 手动更新标题: {session.title}")
        
        # 获取消息数量
        count = SessionService.get_session_message_count(db, session_id)
        print(f"✓ 会话消息数量: {count}")


def run_all_tests():
    """运行所有测试"""
    print("\n" + "🚀" * 25)
    print("开始测试 ModelForge 数据库和认证功能")
    print("🚀" * 25 + "\n")
    
    try:
        # 1. 数据库初始化
        db_manager = test_database_init()
        
        # 2. 用户注册
        user_id = test_user_registration(db_manager)
        if not user_id:
            print("\n✗ 测试失败: 无法创建用户")
            return
        
        # 3. 用户登录
        user_id, token = test_user_login(db_manager)
        if not token:
            print("\n✗ 测试失败: 登录失败")
            return
        
        # 4. Token 验证
        test_token_verification(token)
        
        # 5. 会话管理
        session_id1, session_id2 = test_session_management(db_manager, user_id)
        
        # 6. 消息管理
        test_message_management(db_manager, session_id1)
        
        # 7. 记忆管理
        test_memory_management(db_manager, user_id, session_id1)
        
        # 8. 会话操作
        test_session_operations(db_manager, session_id1)
        
        print("\n" + "✅" * 25)
        print("所有测试通过！")
        print("✅" * 25 + "\n")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_all_tests()
