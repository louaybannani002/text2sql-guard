import { TokenStore } from "./token-store";

describe("TokenStore", () => {
  it("returns the token until shortly before it expires", () => {
    let now = 1_000_000;
    const store = new TokenStore(() => now);
    expect(store.get()).toBeNull();
    store.set("t", 900);
    expect(store.get()).toBe("t");
    now += 889_000;
    expect(store.get()).toBe("t");
    now += 2_000; // inside the 10 s safety margin
    expect(store.get()).toBeNull();
  });

  it("forgets the token on clear", () => {
    const store = new TokenStore();
    store.set("t", 900);
    store.clear();
    expect(store.get()).toBeNull();
  });

  it("never touches web storage", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    new TokenStore().set("t", 900);
    expect(setItem).not.toHaveBeenCalled();
    expect(document.cookie).toBe("");
  });
});
