import { chromium } from 'playwright';

export class ProfileManager {
  constructor({ logger }) {
    this.logger = logger;
    this.contexts = new Map();
    this.activeProfile = 'phantom';
  }

  async getProfile(profile = 'phantom', options = {}) {
    if (this.contexts.has(profile)) {
      this.activeProfile = profile;
      return this.contexts.get(profile);
    }

    let context = null;
    if (profile === 'phantom') {
      context = await chromium.launchPersistentContext(options.userDataDir || './profiles/phantom', {
        headless: options.headless ?? false,
        viewport: { width: 1280, height: 820 },
      });
    } else if (profile === 'user') {
      const wsEndpoint = options.cdpEndpoint || process.env.PHANTOM_CDP_ENDPOINT;
      if (!wsEndpoint) {
        throw new Error('User profile requires PHANTOM_CDP_ENDPOINT for existing session.');
      }
      const browser = await chromium.connectOverCDP(wsEndpoint);
      context = browser.contexts()[0];
    } else if (profile === 'remote') {
      const wsEndpoint = options.cdpEndpoint || process.env.PHANTOM_REMOTE_CDP;
      if (!wsEndpoint) {
        throw new Error('Remote profile requires PHANTOM_REMOTE_CDP endpoint.');
      }
      const browser = await chromium.connectOverCDP(wsEndpoint);
      context = browser.contexts()[0];
    } else {
      throw new Error(`Unknown profile: ${profile}`);
    }

    this.contexts.set(profile, context);
    this.activeProfile = profile;
    this.logger?.info(`Profile ready: ${profile}`);
    return context;
  }

  getActiveProfile() {
    return this.activeProfile;
  }
}
