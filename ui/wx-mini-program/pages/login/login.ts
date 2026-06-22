const app = getApp<IAppOption>();

Page({
  data: {
    loading: false,
    error: '',
  },

  onLoad() {
    // If already logged in, redirect to chat
    if (app.globalData.token) {
      wx.redirectTo({ url: '/pages/chat/chat' });
    }
  },

  async handleLogin() {
    this.setData({ loading: true, error: '' });

    try {
      const loginRes = await new Promise<WechatMiniprogram.LoginSuccessCallbackResult>(
        (resolve, reject) => wx.login({ success: resolve, fail: reject }),
      );

      const res = await new Promise<WechatMiniprogram.RequestSuccessCallbackResult>(
        (resolve, reject) => {
          wx.request({
            url: `${app.globalData.baseUrl}/api/wx/login`,
            method: 'POST',
            data: { code: loginRes.code },
            success: resolve,
            fail: reject,
          });
        },
      );

      if (res.statusCode !== 200) {
        const errData = res.data as { error?: string };
        throw new Error(errData?.error || `Login failed (${res.statusCode})`);
      }

      const data = res.data as { token: string; openid: string };
      app.globalData.token = data.token;
      app.globalData.openid = data.openid;
      wx.setStorageSync('token', data.token);
      wx.setStorageSync('openid', data.openid);

      wx.redirectTo({ url: '/pages/chat/chat' });
    } catch (err: any) {
      this.setData({ error: err.message || '登录失败，请重试' });
    } finally {
      this.setData({ loading: false });
    }
  },
});
