"""
测试会话模型生成器
注意：此测试需要实际的模型文件
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_manager import DatabaseManager
from api.auth_service import AuthService
from pytorch.session_model_generate import SessionModelGenerate


def test_session_model_basic():
    """测试基本的会话模型功能"""
    print("=" * 50)
    print("测试: 会话模型生成器基础功能")
    print("=" * 50)
    
    # 初始化数据库
    db_manager = DatabaseManager()
    
    # 创建测试用户
    with db_manager.get_session() as db:
        success, message, user = AuthService.register_user(
            db,
            username="model_test_user",
            password="test123",
            email="model_test@example.com"
        )
        
        if not success and "已存在" in message:
            user = AuthService.get_user_by_username(db, "model_test_user")
        
        print(f"✓ 测试用户: {user.username} (ID: {user.id})")
    
    # 注意：这里需要一个实际的模型路径
    # 如果没有模型，测试将跳过
    model_path = os.path.join(
        os.path.expanduser("~"),
        "AppData/ai/ai_model/DeepSeek-R1-Distill-Qwen-1.5B"
    )
    
    if not os.path.exists(model_path):
        print(f"\n⚠️  模型路径不存在: {model_path}")
        print("跳过模型加载测试")
        print("\n提示：要完整测试，请：")
        print("1. 下载一个模型到本地")
        print("2. 修改 model_path 变量指向正确的路径")
        return
    
    print(f"\n✓ 模型路径: {model_path}")
    
    try:
        # 创建会话模型生成器
        print("\n正在创建会话模型生成器...")
        generator = SessionModelGenerate(
            user_id=user.id,
            session_id=None,  # 自动创建新会话
            db_manager=db_manager,
            model_path=model_path,
            max_new_tokens=100,
            temperature=0.7
        )
        
        print(f"✓ 会话模型生成器创建成功")
        print(f"  - 会话ID: {generator.session_id}")
        
        # 获取会话信息
        session_info = generator.get_session_info()
        print(f"\n✓ 会话信息:")
        for key, value in session_info.items():
            print(f"  - {key}: {value}")
        
        # 测试对话
        print("\n" + "=" * 50)
        print("测试对话功能")
        print("=" * 50)
        
        # 初始化模型
        print("\n正在加载模型...")
        generator.pipeline_question()
        
        # 第一轮对话
        question1 = "你好，请介绍一下你自己"
        print(f"\n用户: {question1}")
        response1 = generator.pipeline_answer(question1)
        print(f"助手: {response1[:100]}...")
        
        # 第二轮对话（测试上下文记忆）
        question2 = "我刚才问了你什么？"
        print(f"\n用户: {question2}")
        response2 = generator.pipeline_answer(question2)
        print(f"助手: {response2[:100]}...")
        
        # 测试记忆提取
        question3 = "我喜欢使用 Python 编程，我是一名 AI 开发者"
        print(f"\n用户: {question3}")
        response3 = generator.pipeline_answer(question3)
        print(f"助手: {response3[:100]}...")
        
        # 列出所有会话
        print("\n" + "=" * 50)
        print("用户的所有会话")
        print("=" * 50)
        sessions = generator.list_user_sessions()
        for sess in sessions:
            print(f"\n会话 {sess['id']}: {sess['title']}")
            print(f"  - 消息数: {sess['message_count']}")
            print(f"  - 创建时间: {sess['created_at']}")
        
        # 测试会话切换
        if len(sessions) > 1:
            print("\n" + "=" * 50)
            print("测试会话切换")
            print("=" * 50)
            
            new_session_id = sessions[0]['id']
            success = generator.switch_session(new_session_id)
            if success:
                print(f"✓ 成功切换到会话 {new_session_id}")
        
        print("\n✅ 所有测试通过！")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()


def test_memory_injection():
    """测试记忆注入功能"""
    print("\n" + "=" * 50)
    print("测试: 记忆注入功能")
    print("=" * 50)
    
    db_manager = DatabaseManager()
    
    # 获取测试用户
    with db_manager.get_session() as db:
        user = AuthService.get_user_by_username(db, "model_test_user")
        if not user:
            print("✗ 测试用户不存在，请先运行 test_session_model_basic()")
            return
    
    # 手动创建一些记忆
    from api.memory_service import MemoryService
    
    with db_manager.get_session() as db:
        MemoryService.create_memory(
            db, user.id,
            memory_type=MemoryService.MEMORY_TYPE_PREFERENCE,
            key="喜欢",
            value="用户喜欢使用 Python 和深度学习",
            importance=0.9
        )
        
        MemoryService.create_memory(
            db, user.id,
            memory_type=MemoryService.MEMORY_TYPE_FACT,
            key="职业",
            value="用户是一名 AI 工程师",
            importance=0.95
        )
        
        print("✓ 创建了测试记忆")
        
        # 搜索记忆
        memories = MemoryService.get_relevant_memories_for_query(
            db, user.id, "推荐一些编程资源"
        )
        
        print(f"\n✓ 找到 {len(memories)} 条相关记忆:")
        for mem in memories:
            print(f"  - [{mem.memory_type}] {mem.value}")
        
        # 格式化记忆
        context = MemoryService.format_memories_for_context(memories)
        print(f"\n✓ 格式化的记忆上下文:")
        print(context)


if __name__ == "__main__":
    print("\n" + "🧪" * 25)
    print("ModelForge 会话模型测试")
    print("🧪" * 25 + "\n")
    
    # 基础功能测试
    test_session_model_basic()
    
    # 记忆注入测试
    test_memory_injection()
