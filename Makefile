include $(TOPDIR)/rules.mk

PKG_NAME:=luci-app-wifi-data-switch
PKG_VERSION:=0.7.0
PKG_RELEASE:=1
PKG_LICENSE:=MIT
PKGARCH:=all

include $(INCLUDE_DIR)/package.mk

define Package/luci-app-wifi-data-switch
  SECTION:=luci
  CATEGORY:=LuCI
  SUBMENU:=3. Applications
  TITLE:=Wi-Fi and mobile uplink switching and download balancing
  DEPENDS:=+luci-base +python3 +ruby +ruby-yaml +ruby-json +curl +ca-bundle +iw +rpcd-mod-iwinfo +ip-full +nftables
endef

define Build/Compile
endef

define Package/luci-app-wifi-data-switch/install
	$(CP) ./files/* $(1)/
endef

define Package/luci-app-wifi-data-switch/conffiles
/etc/wifi-data-switch/
endef

$(eval $(call BuildPackage,luci-app-wifi-data-switch))
