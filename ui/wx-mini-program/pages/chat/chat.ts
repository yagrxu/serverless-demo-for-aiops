const app = getApp<IAppOption>();

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

interface Cat {
  cat_id: string;
  name: string;
  breed: string;
}

Page({
  data: {
    messages: [] as Message[],
    inputValue: '',
    loading: false,
    cats: [] as Cat[],
    currentCatId: '',
    currentCatName: '',
    sessionId: '',
    scrollToView: '',
  },

  onLoad() {
    if (!app.globalData.token) {
      wx.redirectTo({ url: '/pages/login/login' });
      return;
    }
    this.loadCats();
    this.setData({ sessionId: `wx_${app.globalData.openid}_${Date.now()}` });
  },

  async loadCats() {
    try {
      const res = await new Promise<WechatMiniprogram.RequestSuccessCallbackResult>(
        (resolve, reject) => {
          wx.request({
            url: `${app.globalData.baseUrl}/api/wx/cats`,
            method: 'GET',
            header: { Authorization: `Bearer ${app.globalData.token}` },
            success: resolve,
            fail: reject,
          });
        },
      );

      if (res.statusCode === 401) {
        wx.redirectTo({ url: '/pages/login/login' });
        return;
      }

      const data = res.data as { cats: Cat[] };
      const cats = data.cats || [];
      const savedCatId = app.globalData.currentCatId;
      const currentCat = cats.find(c => c.cat_id === savedCatId) || cats[0];

      this.setData({
        cats,
        currentCatId: currentCat?.cat_id || '',
        currentCatName: currentCat?.name || '',
      });
    } catch (err) {
      console.error('Failed to load cats:', err);
    }
  },

  onCatChange(e: WechatMiniprogram.PickerChange) {
    const idx = Number(e.detail.value);
    const cat = this.data.cats[idx];
    if (cat) {
      this.setData({ currentCatId: cat.cat_id, currentCatName: cat.name });
      app.globalData.currentCatId = cat.cat_id;
      wx.setStorageSync('currentCatId', cat.cat_id);
    }
  },

  onInputChange(e: WechatMiniprogram.Input) {
    this.setData({ inputValue: e.detail.value });
  },

  async sendMessage() {
    const { inputValue, currentCatId, messages, sessionId } = this.data;
    if (!inputValue.trim() || !currentCatId) return;

    const userMsg: Message = { role: 'user', content: inputValue.trim() };
    const assistantMsg: Message = { role: 'assistant', content: '' };
    const newMessages = [...messages, userMsg, assistantMsg];
    const assistantIdx = newMessages.length - 1;

    this.setData({
      messages: newMessages,
      inputValue: '',
      loading: true,
      scrollToView: `msg-${assistantIdx}`,
    });

    try {
      const requestTask = wx.request({
        url: `${app.globalData.baseUrl}/api/wx/chat`,
        method: 'POST',
        header: {
          Authorization: `Bearer ${app.globalData.token}`,
          'Content-Type': 'application/json',
        },
        data: { message: userMsg.content, cat_id: currentCatId, session_id: sessionId },
        enableChunkedTransfer: true,
        success: (res) => {
          if (res.statusCode === 401) {
            wx.redirectTo({ url: '/pages/login/login' });
          }
        },
        fail: (err) => {
          this.appendToAssistant(assistantIdx, '\n[网络错误，请重试]');
        },
      });

      // Handle chunked SSE response
      let buffer = '';
      requestTask.onChunkReceived((res) => {
        const chunk = this.arrayBufferToString(res.data);
        buffer += chunk;

        // Parse SSE events from buffer
        const lines = buffer.split('\n');
        buffer = lines.pop() || ''; // Keep incomplete line in buffer

        let eventType = '';
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7);
          } else if (line.startsWith('data: ')) {
            const data = line.slice(6);
            this.handleSSEEvent(eventType, data, assistantIdx);
            eventType = '';
          }
        }
      });
    } catch (err: any) {
      this.appendToAssistant(assistantIdx, '\n[发送失败，请重试]');
    } finally {
      this.setData({ loading: false });
    }
  },

  handleSSEEvent(event: string, data: string, assistantIdx: number) {
    try {
      const parsed = JSON.parse(data);
      switch (event) {
        case 'token':
          this.appendToAssistant(assistantIdx, parsed.content || '');
          break;
        case 'done':
          this.setData({ loading: false, sessionId: parsed.session_id || this.data.sessionId });
          break;
        case 'error':
          this.appendToAssistant(assistantIdx, `\n[错误: ${parsed.error}]`);
          this.setData({ loading: false });
          break;
      }
    } catch {
      // Ignore malformed events
    }
  },

  appendToAssistant(idx: number, text: string) {
    const key = `messages[${idx}].content`;
    const current = this.data.messages[idx]?.content || '';
    this.setData({
      [key]: current + text,
      scrollToView: `msg-${idx}`,
    });
  },

  arrayBufferToString(buffer: ArrayBuffer): string {
    const bytes = new Uint8Array(buffer);
    let result = '';
    for (let i = 0; i < bytes.length; i++) {
      result += String.fromCharCode(bytes[i]);
    }
    // Handle UTF-8 decoding
    try {
      return decodeURIComponent(escape(result));
    } catch {
      return result;
    }
  },
});
