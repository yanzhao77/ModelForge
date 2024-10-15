import sys

import markdown
from PyQt6.QtWidgets import QApplication, QMainWindow, QTextBrowser, QVBoxLayout, QWidget, QTextEdit


class MarkdownViewer(QMainWindow):
    def __init__(self, markdown_text):
        super().__init__()

        # 将 Markdown 转换成 HTML
        html_content = markdown.markdown(markdown_text)

        # 创建 QTextBrowser 用于显示 HTML
        self.text_browser = QTextEdit()

        # 设置 HTML 内容
        self.text_browser.setHtml(html_content)

        # 设置布局
        layout = QVBoxLayout()
        layout.addWidget(self.text_browser)

        # 创建一个 widget 作为主窗口的中心部件
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # 设置窗口标题和大小
        self.setWindowTitle('Markdown Viewer')
        self.resize(800, 600)

# 示例 Markdown 文本
markdown_text = """
# Hello, World!

This is a simple **Markdown** example.

- Item 1
- Item 2
- Item 3

开始对话，输入 'exit' 退出。你: 写一个Java的冒泡排序模型: 写一个Java的冒泡排序 当然！以下是一个简单的Java冒泡排序示例：
```java public class BubbleSort { public static void main(String[] args) { int[] numbers = {64, 34, 25, 12, 22, 11, 90}; bubbleSort(numbers); System.out.println("Sorted array: "); printArray(numbers); }
public static void bubbleSort(int[] arr) {
    int n = arr.length;
    for (int i = 0; i < n - 1; i++) {
        for (int j = 0; j < n - i - 1; j++) {
            if (arr[j] > arr[j + 1]) {
                int temp = arr[j];
                arr[j] = arr[j + 1];
                arr[j + 1] = temp;
            }
        }
    }
}

public static void printArray(int[] arr) {
    for (int value : arr) {
        System.out.print(value + " ");
    }
    System.out.println();
}

} ```
这个程序定义了一个bubbleSort方法，它接受一个整数数组作为参数，然后执行冒泡排序。冒泡排序是一种简单直观的排序算法，它重复地遍历要排序的数组，比较每个元素与相邻未排序元素的大小，并交换它们的顺序。通过这些元素的持续比较和交换，数组最终有序。
执行main方法时，将传入的数组 {64, 34, 25, 12, 22, 11, 90} 确保所有元素都在 0 到 9 中，然后调用bubbleSort方法并打印排序后的数组。最后，调用printArray方法打印排序后的数组。
"""

# 创建应用实例
app = QApplication(sys.argv)

# 创建 Markdown 查看器实例
viewer = MarkdownViewer(markdown_text)
viewer.show()

# 运行应用的事件循环
sys.exit(app.exec())