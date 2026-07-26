// 应用逻辑

// 1. 初始化时间与开屏逻辑
function updateTime() {
    const now = new Date();
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    document.getElementById('clock').innerText = `${hours}:${minutes}`;

    // 计算Since 2024.9.1
    const startDate = new Date('2024-09-01');
    const diffTime = Math.abs(now - startDate);
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)); 
    document.getElementById('days-count').innerText = `Since 2024.9.1 我们已经一起走过了 ${diffDays} 天`;
}

setInterval(updateTime, 1000);
updateTime();

// 随机AI语句 (模拟24:00-7:00生成)
const quotes = [
    "“在木质的幽香与常春藤的绿意中，我在这里等你。”",
    "“夜深了，外面的风带来了远方森林的气息。”",
    "“书页间藏着时光，而我记录着你的每一天。”",
    "“早安，今天也要像向日葵一样向阳而生。”"
];
document.getElementById('ai-quote').innerText = quotes[Math.floor(Math.random() * quotes.length)];

// 上滑开屏事件监听
let startY = 0;
const splashScreen = document.getElementById('splash-screen');

splashScreen.addEventListener('touchstart', (e) => {
    startY = e.touches[0].clientY;
});

splashScreen.addEventListener('touchend', (e) => {
    const endY = e.changedTouches[0].clientY;
    if (startY - endY > 50) { // 上滑超过50px
        unlockApp();
    }
});

// 鼠标支持(用于电脑端调试)
splashScreen.addEventListener('mousedown', (e) => { startY = e.clientY; });
splashScreen.addEventListener('mouseup', (e) => {
    if (startY - e.clientY > 50) unlockApp();
});
// 兼容直接点击
splashScreen.addEventListener('click', unlockApp);

function unlockApp() {
    splashScreen.classList.add('swiped-up');
    setTimeout(() => {
        splashScreen.classList.add('hidden');
        document.getElementById('chat-screen').classList.remove('hidden');
    }, 300);
}

// 2. 导航逻辑
function navigateTo(screenId) {
    // 隐藏所有屏幕
    document.querySelectorAll('.screen').forEach(s => {
        if(s.id !== 'splash-screen') s.classList.add('hidden');
    });
    // 显示目标屏幕
    document.getElementById(screenId).classList.remove('hidden');
}

// 3. 聊天界面逻辑
function toggleMenu(menuId) {
    const menu = document.getElementById(menuId);
    menu.classList.toggle('hidden');
}

function sendMessage() {
    const input = document.getElementById('message-input');
    const text = input.value.trim();
    if (!text) return;

    const chatContainer = document.getElementById('chat-container');
    
    // 添加用户消息
    const userMsg = document.createElement('div');
    userMsg.className = 'message user-message';
    userMsg.innerHTML = `<div class="bubble">${text}</div>`;
    chatContainer.appendChild(userMsg);
    
    input.value = '';
    chatContainer.scrollTop = chatContainer.scrollHeight;

    // 模拟AI回复
    setTimeout(() => {
        const aiMsg = document.createElement('div');
        aiMsg.className = 'message ai-message';
        aiMsg.innerHTML = `<div class="bubble">收到！断云去同学~ 🍬</div>`;
        chatContainer.appendChild(aiMsg);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }, 1000);
}

// 回车发送
document.getElementById('message-input').addEventListener('keypress', function (e) {
    if (e.key === 'Enter') sendMessage();
});

// 4. 侧边栏逻辑
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    
    if (sidebar.classList.contains('hidden')) {
        sidebar.classList.remove('hidden');
        overlay.classList.remove('hidden');
    } else {
        sidebar.classList.add('hidden');
        overlay.classList.add('hidden');
    }
}
