# query_buffer.py
import queue

class QueryBuffer:
    def __init__(self, max_size):
        self.max_size = max_size
        self.buffer = queue.Queue(max_size)

    def enqueue(self, query):
        if self.buffer.full():
            print("Query buffer is full.")
        else:
            self.buffer.put(query)

    def dequeue(self):
        return self.buffer.get()
