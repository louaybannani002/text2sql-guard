-- The 0003 comment says this column matches customer/seller zip codes, which t2s_reader can
-- no longer read (0004). The catalog shows this comment to the LLM, so remove the dead hint.
COMMENT ON COLUMN shop.geolocations.geolocation_zip_code_prefix IS
    'First five digits of a postal code (CEP). Customer and seller zip codes are restricted, so use this only for geolocation-level analysis.';
