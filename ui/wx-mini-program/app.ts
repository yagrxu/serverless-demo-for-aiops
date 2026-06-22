export interface IAppOption {
  globalData: {
    token: string;
    openid: string;
    baseUrl: string;
    currentCatId: string;
  };
}

App<IAppOption>({
  globalData: {
    token: '',
    openid: '',
    baseUrl: '', // Set via env or hardcode for demo
    currentCatId: '',
  },

  onLaunch() {
    // Check if already logged in
    const token = wx.getStorageSync('token');
    if (token) {
      this.globalData.token = token;
      this.globalData.openid = wx.getStorageSync('openid') || '';
      this.globalData.currentCatId = wx.getStorageSync('currentCatId') || '';
    }

    // Set base URL from build-time config
    this.globalData.baseUrl = '__BASE_URL__'; // replaced at build time
  },
});
