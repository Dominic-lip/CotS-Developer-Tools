#pragma once
#include "Domains/CotSDomainToolset.h"
class ICotSAssetsDomain : public ICotSDomainToolset { public: virtual FString GetDomainName() const override { return TEXT("Assets"); } };
